from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import logging
from pyairtable import Table
from datetime import datetime
import uuid
import requests

# Initialiser Flask
app = Flask(__name__)

# Configurer CORS
CORS(app)

# Configurer les logs
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Charger la clé API d'OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.error("La clé API d'OpenAI (OPENAI_API_KEY) n'est pas définie dans les variables d'environnement.")
    raise ValueError("La clé API d'OpenAI n'est pas définie.")

openai.api_key = OPENAI_API_KEY

# Configuration Airtable
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME_CONTEXT = "Context"  # Nom de la table pour le contexte
TABLE_NAME_CONVERSATIONS = "Conversations"
TABLE_NAME_MESSAGES = "Messages"

if not AIRTABLE_API_KEY or not BASE_ID:
    logger.error("Les informations d'Airtable (API_KEY ou BASE_ID) ne sont pas définies.")
    raise ValueError("Les informations d'Airtable ne sont pas définies.")

airtable_context = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_NAME_CONTEXT)
airtable_conversations = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_NAME_CONVERSATIONS)
airtable_messages = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_NAME_MESSAGES)

# Fonction pour envoyer un message sur Slack
def send_slack_message(text, channel="#conversationsite", thread_ts=None):
    try:
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if not slack_token:
            logger.error("Le token Slack (SLACK_BOT_TOKEN) n'est pas défini dans les variables d'environnement.")
            return None

        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {slack_token}",
            "Content-Type": "application/json"
        }
        data = {
            "channel": channel,
            "text": text
        }

        if thread_ts:
            data["thread_ts"] = thread_ts

        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200 and response.json().get("ok"):
            logger.info(f"Message Slack envoyé : {text}")
            return response.json().get("ts")  # Retourner le timestamp du message
        else:
            logger.error(f"Erreur lors de l'envoi du message Slack : {response.text}")
            return None
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du message Slack : {e}")
        return None

# Fonction pour charger le contexte initial depuis Airtable
def load_context_from_airtable():
    try:
        records = airtable_context.all(max_records=1, sort=["Timestamp"])
        if not records:
            logger.error("Aucun contexte trouvé dans Airtable.")
            return []

        first_record = records[0]["fields"]
        context = [{"role": first_record["Role"], "content": first_record["Content"]}]
        logger.info("Contexte initial chargé avec succès depuis Airtable.")
        return context
    except Exception as e:
        logger.error(f"Erreur lors du chargement du contexte depuis Airtable : {e}")
        return []

# Charger le contexte initial
context = load_context_from_airtable()

if not context:
    logger.error("Impossible de démarrer l'application sans contexte initial.")
    raise ValueError("Contexte initial manquant.")

# Fonction pour créer une nouvelle conversation
def create_conversation(user=None):
    try:
        conversation_id = str(uuid.uuid4())
        data = {
            "ConversationID": conversation_id,
            "User": user or "anonymous",
            "StartTimestamp": datetime.now().isoformat()
        }
        record = airtable_conversations.create(data)
        record_id = record["id"]

        # Envoyer un message Slack et récupérer le thread_ts
        thread_ts = send_slack_message(":taurus: Une conversation vient de démarrer sur le site du Minotaure.")
        if thread_ts:
            airtable_conversations.update(record_id, {"SlackThreadTS": str(thread_ts)})

        logger.info(f"Nouvelle conversation créée avec Record ID : {record_id}")
        return record_id, thread_ts
    except Exception as e:
        logger.error(f"Erreur lors de la création de la conversation : {e}")
        return None, None

# Fonction pour enregistrer un message
def save_message(conversation_record_id, role, content):
    try:
        message_id = str(uuid.uuid4())
        data = {
            "MessageID": message_id,
            "ConversationID": [conversation_record_id],
            "Role": role,
            "Content": content,
            "Timestamp": datetime.now().isoformat()
        }
        airtable_messages.create(data)

        logger.info(f"Message enregistré avec succès : {data}")
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement du message : {e}")

@app.route("/chat", methods=["POST"])
def chat_with_minotaure():
    try:
        user_message = request.json.get("message", "")
        user_id = request.json.get("user", "anonymous")
        conversation_id = request.json.get("conversation_id")

        if not user_message:
            return jsonify({"error": "Message non fourni"}), 400

        # Si une conversation n'existe pas encore, la créer
        if not conversation_id:
            conversation_id, thread_ts = create_conversation(user=user_id)
            if not conversation_id:
                return jsonify({"error": "Impossible de créer une conversation"}), 500
        else:
            # Récupérer le thread_ts de la conversation existante
            logger.debug(f"Recherche de la conversation avec ID : {conversation_id}")
            try:
                records = airtable_conversations.all(formula=f"{{ConversationID}} = '{conversation_id}'")
                logger.debug(f"Résultats de la requête Airtable : {records}")
                if len(records) > 0:
                    thread_ts = records[0]["fields"].get("SlackThreadTS")
                    logger.debug(f"Thread Slack récupéré : {thread_ts}")
                    if not thread_ts:
                        logger.error(f"Thread Slack introuvable pour la conversation ID : {conversation_id}")
                        return jsonify({"error": "Thread Slack introuvable"}), 500
                else:
                    logger.error(f"Aucun enregistrement trouvé pour ID : {conversation_id}")
                    return jsonify({"error": "Conversation introuvable"}), 404
            except Exception as e:
                logger.error(f"Erreur lors de la requête Airtable : {e}")
                return jsonify({"error": "Erreur interne"}), 500

        # Enregistrer le message utilisateur
        save_message(conversation_id, "user", user_message)

        # Ajouter le message utilisateur au contexte
        context.append({"role": "user", "content": user_message})
        logger.debug(f"Contexte avant appel OpenAI : {context}")

        # Appeler OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=context,
            temperature=0.5,
            max_tokens=500
        )

        # Récupérer et enregistrer la réponse
        assistant_message = response["choices"][0]["message"]["content"]
        context.append({"role": "assistant", "content": assistant_message})
        save_message(conversation_id, "assistant", assistant_message)

        # Envoyer les messages au thread Slack
        send_slack_message(f":bust_in_silhouette: Visiteur : {user_message}", thread_ts=thread_ts)
        send_slack_message(f":taurus: Minotaure : {assistant_message}", thread_ts=thread_ts)

        return jsonify({
            "response": assistant_message,
            "conversation_id": conversation_id
        })
    except Exception as e:
        logger.error(f"Erreur dans l'endpoint '/chat': {e}")
        return jsonify({"error": str(e)}), 500



# Endpoint de vérification de santé
@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

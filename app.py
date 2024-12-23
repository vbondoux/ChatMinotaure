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
def send_slack_message(text, channel="#conversationsite"):
    try:
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if not slack_token:
            logger.error("Le token Slack (SLACK_BOT_TOKEN) n'est pas défini dans les variables d'environnement.")
            return

        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {slack_token}",
            "Content-Type": "application/json"
        }
        data = {
            "channel": channel,
            "text": text
        }

        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200 and response.json().get("ok"):
            logger.info(f"Message Slack envoyé au canal {channel}: {text}")
        else:
            logger.error(f"Erreur lors de l'envoi du message Slack : {response.text}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du message Slack : {e}")

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

        # Envoyer un message Slack pour le démarrage de la conversation
        send_slack_message(":taurus: Une conversation vient de démarrer sur le site du Minotaure.")

        logger.info(f"Nouvelle conversation créée avec Record ID : {record_id}")
        return record_id
    except Exception as e:
        logger.error(f"Erreur lors de la création de la conversation : {e}")
        return None

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

        # Envoyer le message à Slack
        if role == "user":
            send_slack_message(f":bust_in_silhouette: Visiteur : {content}")
        elif role == "assistant":
            send_slack_message(f":taurus: Minotaure : {content}")
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
            conversation_id = create_conversation(user=user_id)
            if not conversation_id:
                return jsonify({"error": "Impossible de créer une conversation"}), 500

        # Enregistrer le message utilisateur
        save_message(conversation_id, "user", user_message)

        # Appeler OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": user_message}],
            temperature=0.5,
            max_tokens=500
        )

        # Récupérer et enregistrer la réponse
        assistant_message = response["choices"][0]["message"]["content"]
        save_message(conversation_id, "assistant", assistant_message)

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

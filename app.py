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
CORS(app)

# Configurer les logs
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Charger les clés API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

if not OPENAI_API_KEY or not AIRTABLE_API_KEY or not BASE_ID or not SLACK_BOT_TOKEN or not SLACK_WEBHOOK_URL:
    raise ValueError("Les variables d'environnement nécessaires ne sont pas toutes définies.")

openai.api_key = OPENAI_API_KEY

# Configuration Airtable
TABLE_NAME_CONTEXT = "Context"
TABLE_NAME_CONVERSATIONS = "Conversations"
TABLE_NAME_MESSAGES = "Messages"
airtable_context = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_NAME_CONTEXT)
airtable_conversations = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_NAME_CONVERSATIONS)
airtable_messages = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_NAME_MESSAGES)

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
def create_new_conversation():
    try:
        conversation_id = str(uuid.uuid4())
        logger.debug(f"Tentative de création d'une conversation avec ID : {conversation_id}")
        record = airtable_conversations.create({
            "ConversationID": conversation_id,
            "Mode": "automatique",
            "StartTimestamp": datetime.now().isoformat()
        })
        logger.info(f"Nouvelle conversation créée avec l'ID : {conversation_id}")
        return conversation_id
    except Exception as e:
        logger.error(f"Erreur lors de la création d'une nouvelle conversation : {e}")
        return None

# Fonction pour envoyer un message à Slack
def send_message_to_slack(channel, text):
    try:
        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"}
        data = {"channel": channel, "text": text}

        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Erreur lors de l'envoi à Slack : {response.text}")
            return False
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi à Slack : {e}")
        return False

# Route principale du chatbot
@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "")
    conversation_id = request.json.get("conversation_id")

    if not user_message:
        return jsonify({"error": "Message manquant"}), 400

    # Si aucun conversation_id n'est fourni ou si la conversation est introuvable, créer une nouvelle conversation
    if not conversation_id:
        conversation_id = create_new_conversation()
        if not conversation_id:
            return jsonify({"error": "Erreur lors de la création d'une nouvelle conversation"}), 500
    else:
        try:
            record = airtable_conversations.first(formula=f"{{ConversationID}} = '{conversation_id}'")
            if not record:
                conversation_id = create_new_conversation()
                if not conversation_id:
                    return jsonify({"error": "Erreur lors de la création d'une nouvelle conversation"}), 500
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de la conversation : {e}")
            return jsonify({"error": "Erreur lors de la vérification de la conversation"}), 500

    # Récupérer le mode de la conversation
    try:
        record = airtable_conversations.first(formula=f"{{ConversationID}} = '{conversation_id}'")
        mode = record["fields"].get("Mode", "automatique")
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du mode : {e}")
        return jsonify({"error": "Erreur lors de la récupération du mode"}), 500

    # Enregistrer le message de l'utilisateur dans Airtable
    try:
        airtable_messages.create({
            "ConversationID": [record["id"]],
            "Role": "user",
            "Content": user_message,
            "Timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement du message utilisateur : {e}")
        return jsonify({"error": "Erreur lors de l'enregistrement du message utilisateur"}), 500

    # Si le mode est manuel, rediriger vers Slack
    if mode == "manuel":
        if send_message_to_slack("#conversationsite", f":bust_in_silhouette: Visiteur : {user_message} (ID: {conversation_id})"):
            return jsonify({"message": "Message envoyé à Slack", "conversation_id": conversation_id}), 200
        else:
            return jsonify({"error": "Erreur lors de l'envoi à Slack"}), 500

    # Mode automatique (logique IA actuelle)
    try:
        enriched_context = context + [{"role": "user", "content": user_message}]
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=enriched_context,
            temperature=0.5,
            max_tokens=500
        )
        assistant_message = response["choices"][0]["message"]["content"]

        # Enregistrer la réponse de l'assistant dans Airtable
        airtable_messages.create({
            "ConversationID": [record["id"]],
            "Role": "assistant",
            "Content": assistant_message,
            "Timestamp": datetime.now().isoformat()
        })

        return jsonify({"response": assistant_message, "conversation_id": conversation_id}), 200
    except Exception as e:
        logger.error(f"Erreur dans le mode automatique : {e}")
        return jsonify({"error": "Erreur lors de la génération de la réponse"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

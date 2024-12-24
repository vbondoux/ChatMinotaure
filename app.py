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

if not OPENAI_API_KEY or not AIRTABLE_API_KEY or not BASE_ID or not SLACK_BOT_TOKEN:
    raise ValueError("Les variables d'environnement nécessaires ne sont pas toutes définies.")

openai.api_key = OPENAI_API_KEY

# Configuration Airtable
TABLE_NAME_CONVERSATIONS = "Conversations"
TABLE_NAME_MESSAGES = "Messages"
airtable_conversations = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_NAME_CONVERSATIONS)
airtable_messages = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_NAME_MESSAGES)

# Fonction pour envoyer un message sur Slack
def send_slack_message(text, channel="#conversationsite"):
    try:
        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
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
            "StartTimestamp": datetime.now().isoformat(),
            "Mode": "automatique"
        }
        record = airtable_conversations.create(data)
        record_id = record["id"]

        # Envoyer une notification Slack avec l'ID de la conversation
        send_slack_message(f":taurus: Nouvelle conversation créée ! ID : `{conversation_id}`")

        logger.info(f"Nouvelle conversation créée avec Record ID : {record_id}")
        return conversation_id
    except Exception as e:
        logger.error(f"Erreur lors de la création de la conversation : {e}")
        return None

# Route principale du chatbot
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_message = request.json.get("message", "")
        conversation_id = request.json.get("conversation_id")

        if not user_message:
            return jsonify({"error": "Message manquant"}), 400

        # Si aucun conversation_id, créer une nouvelle conversation
        if not conversation_id:
            conversation_id = create_conversation(user="Visiteur")

        # Logique IA ou redirection vers Slack
        assistant_message = "Votre réponse ici."  # Placeholder pour tester

        # Enregistrer les messages dans Airtable
        airtable_messages.create({
            "ConversationID": [conversation_id],
            "Role": "user",
            "Content": user_message,
            "Timestamp": datetime.now().isoformat()
        })

        airtable_messages.create({
            "ConversationID": [conversation_id],
            "Role": "assistant",
            "Content": assistant_message,
            "Timestamp": datetime.now().isoformat()
        })

        return jsonify({
            "response": assistant_message,
            "conversation_id": conversation_id
        }), 200

    except Exception as e:
        logger.error(f"Erreur dans le endpoint '/chat': {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

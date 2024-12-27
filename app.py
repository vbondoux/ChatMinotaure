import os
import uuid
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from pyairtable import Api, Base
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Configuration
AIRTABLE_API_KEY = os.getenv('AIRTABLE_API_KEY')
BASE_ID = os.getenv('AIRTABLE_BASE_ID')
TABLE_NAME_CONTEXT = 'Context'
TABLE_NAME_CONVERSATIONS = 'Conversations'
TABLE_NAME_MESSAGES = 'Messages'
SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN')
SLACK_CHANNEL = '#conversationsite'

# Initialisation
app = Flask(__name__)
api = Api(AIRTABLE_API_KEY)
base = api.base(BASE_ID)
airtable_context = base.table(TABLE_NAME_CONTEXT)
airtable_conversations = base.table(TABLE_NAME_CONVERSATIONS)
airtable_messages = base.table(TABLE_NAME_MESSAGES)
slack_client = WebClient(token=SLACK_BOT_TOKEN)

# Configuration des logs
logging.basicConfig(level=logging.DEBUG)

# Récupérer le contexte initial
def get_initial_context():
    logging.debug("Récupération du contexte depuis Airtable.")
    try:
        records = airtable_context.all(sort=[{"field": "Timestamp", "direction": "asc"}], max_records=1)
        if records:
            context = records[0]['fields']['Content']
            logging.info("Contexte initial chargé avec succès depuis Airtable.")
            return context
        else:
            logging.error("Aucun contexte trouvé dans Airtable.")
            return "Contexte par défaut."
    except Exception as e:
        logging.error(f"Erreur lors de la récupération du contexte : {e}")
        return "Contexte par défaut."

# Créer une nouvelle conversation
def create_conversation(slack_thread_ts):
    try:
        conversation_id = str(uuid.uuid4())
        record = airtable_conversations.create({
            "ConversationID": conversation_id,
            "Timestamp": datetime.utcnow().isoformat(),
            "SlackThreadTS": slack_thread_ts
        })
        logging.info(f"Nouvelle conversation créée avec Record ID : {record['id']}")
        return conversation_id
    except Exception as e:
        logging.error(f"Erreur lors de la création de la conversation : {e}")
        return None

# Enregistrer un message dans Airtable
def log_message(conversation_id, role, content):
    try:
        message_id = str(uuid.uuid4())
        record = airtable_messages.create({
            "MessageID": message_id,
            "ConversationID": [conversation_id],
            "Role": role,
            "Content": content,
            "Timestamp": datetime.utcnow().isoformat()
        })
        logging.info(f"Message enregistré avec succès : {record}")
    except Exception as e:
        logging.error(f"Erreur lors de l'enregistrement du message : {e}")

# Envoyer un message sur Slack
def send_slack_message(content, thread_ts=None):
    try:
        response = slack_client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text=content,
            thread_ts=thread_ts
        )
        logging.info(f"Message Slack envoyé : {content}")
        return response['ts']
    except SlackApiError as e:
        logging.error(f"Erreur lors de l'envoi du message Slack : {e.response['error']}")
        return None

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        user_message = data.get("message", "").strip()

        # Récupérer ou créer une conversation
        context = get_initial_context()
        slack_thread_ts = send_slack_message(":taurus: Une conversation vient de démarrer sur le site du Minotaure.")
        conversation_id = create_conversation(slack_thread_ts)

        if not conversation_id:
            return jsonify({"error": "Erreur lors de la création de la conversation."}), 500

        log_message(conversation_id, "user", user_message)
        send_slack_message(f":bust_in_silhouette: Visiteur : {user_message}", thread_ts=slack_thread_ts)

        # Préparer la réponse
        openai_context = [{"role": "system", "content": context}, {"role": "user", "content": user_message}]
        openai_response = {"role": "assistant", "content": "Réponse fictive pour tester."}

        log_message(conversation_id, "assistant", openai_response["content"])
        send_slack_message(f":taurus: Minotaure : {openai_response['content']}", thread_ts=slack_thread_ts)

        return jsonify({"response": openai_response["content"]})
    except Exception as e:
        logging.error(f"Erreur dans l'endpoint '/chat': {e}")
        return jsonify({"error": "Erreur interne du serveur"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

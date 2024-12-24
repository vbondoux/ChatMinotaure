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

# Fonction pour mettre à jour le mode dans Airtable
def update_mode(conversation_id, mode):
    try:
        airtable_conversations.update_by_field("ConversationID", conversation_id, {"Mode": mode})
        logger.info(f"Mode mis à jour pour la conversation {conversation_id} : {mode}")
        return True
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du mode : {e}")
        return False

# Route pour gérer les commandes Slack
@app.route("/slack-command", methods=["POST"])
def slack_command():
    data = request.form
    command_text = data.get("text", "").strip()
    conversation_id = data.get("conversation_id")

    if not conversation_id:
        return jsonify({"text": "Erreur : Aucun ID de conversation fourni."}), 400

    if command_text.lower() == "le minotaure est là":
        if update_mode(conversation_id, "manuel"):
            return jsonify({"text": f"La conversation {conversation_id} est maintenant en mode manuel."}), 200
        else:
            return jsonify({"text": "Erreur lors de la mise à jour du mode."}), 500

    elif command_text.lower() == "le minotaure part":
        if update_mode(conversation_id, "automatique"):
            return jsonify({"text": f"La conversation {conversation_id} est maintenant en mode automatique."}), 200
        else:
            return jsonify({"text": "Erreur lors de la mise à jour du mode."}), 500

    else:
        return jsonify({"text": "Commande non reconnue. Essayez 'le Minotaure est là' ou 'le Minotaure part'."}), 400

# Route principale du chatbot
@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "")
    conversation_id = request.json.get("conversation_id")

    if not user_message or not conversation_id:
        return jsonify({"error": "Message ou ID de conversation manquant"}), 400

    # Récupérer le mode de la conversation
    try:
        record = airtable_conversations.first(formula=f"{{ConversationID}} = '{conversation_id}'")
        if not record:
            return jsonify({"error": "Conversation introuvable"}), 404
        mode = record["fields"].get("Mode", "automatique")
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du mode : {e}")
        return jsonify({"error": "Erreur lors de la récupération du mode"}), 500

    # Si le mode est manuel, rediriger vers Slack
    if mode == "manuel":
        try:
            url = "https://slack.com/api/chat.postMessage"
            headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
            data = {
                "channel": "#conversationsite",
                "text": f":bust_in_silhouette: Visiteur : {user_message} (ID: {conversation_id})"
            }
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                return jsonify({"message": "Message envoyé à Slack"}), 200
            else:
                logger.error(f"Erreur lors de l'envoi à Slack : {response.text}")
                return jsonify({"error": "Erreur lors de l'envoi à Slack"}), 500
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi à Slack : {e}")
            return jsonify({"error": "Erreur lors de l'envoi à Slack"}), 500

    # Mode automatique (logique IA actuelle)
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": user_message}],
            temperature=0.5,
            max_tokens=500
        )
        assistant_message = response["choices"][0]["message"]["content"]

        # Enregistrer le message dans Airtable
        airtable_messages.create({
            "ConversationID": [conversation_id],
            "Role": "assistant",
            "Content": assistant_message,
            "Timestamp": datetime.now().isoformat()
        })

        return jsonify({"response": assistant_message}), 200
    except Exception as e:
        logger.error(f"Erreur dans le mode automatique : {e}")
        return jsonify({"error": "Erreur lors de la génération de la réponse"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

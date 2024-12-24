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

# Route pour valider le webhook Slack
@app.route("/slack-response", methods=["POST"])
def slack_response():
    data = request.json

    # Validation initiale de Slack (challenge)
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]}), 200

    # Gestion des messages Slack après validation
    conversation_id = data.get("conversation_id")
    message = data.get("text")

    if not conversation_id or not message:
        return jsonify({"error": "ID de conversation ou message manquant"}), 400

    # Enregistrer la réponse dans Airtable
    try:
        airtable_messages.create({
            "ConversationID": [conversation_id],
            "Role": "assistant",
            "Content": message,
            "Timestamp": datetime.now().isoformat()
        })
        logger.info(f"Réponse Slack enregistrée pour la conversation {conversation_id}")
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement de la réponse Slack : {e}")
        return jsonify({"error": "Erreur lors de l'enregistrement du message"}), 500

    # Relayer au client (ajoutez ici votre logique si nécessaire)
    return jsonify({"message": "Réponse relayée avec succès"}), 200

# Endpoint de vérification de santé
@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import logging
from pyairtable import Api
from datetime import datetime
import uuid
import requests
import hashlib
import hmac
import time

# Initialiser Flask
app = Flask(__name__)

# Configurer CORS
CORS(app)

# Configurer les logs
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Charger les clés API d'OpenAI et d'Airtable
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
SLACK_MANUAL_BOT_TOKEN = os.getenv("SLACK_MANUAL_BOT_TOKEN")
SLACK_MANUAL_SIGNING_SECRET = os.getenv("SLACK_MANUAL_SIGNING_SECRET")

# Vérification des variables d'environnement
if not all([OPENAI_API_KEY, AIRTABLE_API_KEY, BASE_ID, SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET]):
    logger.error("Les clés API ou les variables d'environnement sont manquantes.")
    raise ValueError("Configuration incomplète.")

openai.api_key = OPENAI_API_KEY
api = Api(AIRTABLE_API_KEY)
base = api.base(BASE_ID)
airtable_context = base.table("Context")
airtable_conversations = base.table("Conversations")
airtable_messages = base.table("Messages")

# Fonction pour vérifier les requêtes Slack
def verify_slack_request(request, signing_secret):
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False

    slack_signature = request.headers.get("X-Slack-Signature")
    request_body = request.get_data(as_text=True)
    sig_basestring = f"v0:{timestamp}:{request_body}"

    my_signature = "v0=" + hmac.new(
        signing_secret.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(my_signature, slack_signature)

# Fonction pour envoyer un message sur Slack
def send_slack_message(text, channel="#conversationsite", thread_ts=None, manual=False):
    try:
        slack_token = SLACK_MANUAL_BOT_TOKEN if manual else SLACK_BOT_TOKEN
        if not slack_token:
            raise ValueError("Token Slack non défini.")

        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {slack_token}",
            "Content-Type": "application/json"
        }
        data = {"channel": channel, "text": text}

        if thread_ts:
            data["thread_ts"] = thread_ts

        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200 and response.json().get("ok"):
            logger.info(f"Message Slack envoyé : {text}")
            return response.json().get("ts")
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
        return [{"role": first_record["Role"], "content": first_record["Content"]}]
    except Exception as e:
        logger.error(f"Erreur lors du chargement du contexte depuis Airtable : {e}")
        return []

# Fonction pour créer une nouvelle conversation
def create_conversation(user=None):
    try:
        conversation_id = str(uuid.uuid4())
        data = {
            "ConversationID": conversation_id,
            "User": user or "anonymous",
            "StartTimestamp": datetime.now().isoformat(),
            "Mode": "Automatique"
        }
        record = airtable_conversations.create(data)
        record_id = record["id"]

        thread_ts = send_slack_message(":taurus: Une conversation vient de démarrer sur le site du Minotaure.")
        if thread_ts:
            airtable_conversations.update(record_id, {"SlackThreadTS": thread_ts})

        logger.info(f"Nouvelle conversation créée avec Record ID : {record_id}, thread_ts : {thread_ts}")
        return conversation_id, thread_ts
    except Exception as e:
        logger.error(f"Erreur lors de la création de la conversation : {e}")
        return None, None

@app.route("/chat", methods=["POST"])
def chat_with_minotaure():
    try:
        user_message = request.json.get("message", "")
        user_id = request.json.get("user", "anonymous")
        conversation_id = request.json.get("conversation_id")

        if not user_message:
            return jsonify({"error": "Message non fourni"}), 400

        if not conversation_id:
            conversation_id, thread_ts = create_conversation(user=user_id)
            if not conversation_id:
                return jsonify({"error": "Impossible de créer une conversation"}), 500
            context = load_context_from_airtable()
        else:
            records = airtable_conversations.all(formula=f"{{ConversationID}} = '{conversation_id}'")
            if records:
                thread_ts = records[0]["fields"].get("SlackThreadTS")
                mode = records[0]["fields"].get("Mode", "Automatique")
                if mode == "Manuel":
                    return jsonify({"error": "Mode manuel actif, aucune réponse automatique"}), 200

                context = load_context_from_airtable()
                messages = airtable_messages.all(formula=f"{{ConversationID}} = '{conversation_id}'", sort=["Timestamp"])
                for msg in messages:
                    context.append({"role": msg["fields"]["Role"], "content": msg["fields"]["Content"]})
            else:
                return jsonify({"error": "Conversation introuvable"}), 404

        save_message(conversation_id, "user", user_message)
        context.append({"role": "user", "content": user_message})

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=context,
            temperature=0.5,
            max_tokens=500
        )

        assistant_message = response["choices"][0]["message"]["content"]
        context.append({"role": "assistant", "content": assistant_message})
        save_message(conversation_id, "assistant", assistant_message)

        send_slack_message(f":bust_in_silhouette: Visiteur : {user_message}", thread_ts=thread_ts)
        send_slack_message(f":taurus: Minotaure : {assistant_message}", thread_ts=thread_ts)

        return jsonify({"response": assistant_message, "conversation_id": conversation_id})
    except Exception as e:
        logger.error(f"Erreur dans l'endpoint '/chat': {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/slack/events", methods=["POST"])
def slack_events():
    if not verify_slack_request(request, SLACK_MANUAL_SIGNING_SECRET):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        data = request.json
        if "event" in data:
            event = data["event"]
            if event.get("type") == "message" and not event.get("bot_id"):
                user_message = event.get("text")
                channel_id = event.get("channel")
                thread_ts = event.get("thread_ts")

                records = airtable_conversations.all(formula=f"{{SlackThreadTS}} = '{thread_ts}'")
                if records:
                    mode = records[0]["fields"].get("Mode", "Automatique")
                    if mode == "Manuel":
                        send_slack_message(f":taurus: {user_message}", channel=channel_id, thread_ts=thread_ts, manual=True)

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Erreur dans l'endpoint Slack events : {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

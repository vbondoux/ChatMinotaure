# app.py

from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import logging
from pyairtable import Api
from datetime import datetime, timezone
import uuid
import requests
import hashlib
import hmac
import time
from flask_socketio import SocketIO, emit

# Initialiser Flask
app = Flask(__name__)

# Configurer CORS
CORS(app)

# Configurer SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Configurer les logs
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Charger les clés API et secrets
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_MANUAL_BOT_TOKEN = os.getenv("SLACK_MANUAL_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
SLACK_MANUAL_SIGNING_SECRET = os.getenv("SLACK_MANUAL_SIGNING_SECRET")

if not all([OPENAI_API_KEY, AIRTABLE_API_KEY, BASE_ID, SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, SLACK_MANUAL_BOT_TOKEN, SLACK_MANUAL_SIGNING_SECRET]):
    logger.error("Les clés API ou les variables d'environnement sont manquantes.")
    raise ValueError("Configuration incomplète.")

openai.api_key = OPENAI_API_KEY
api = Api(AIRTABLE_API_KEY)
base = api.base(BASE_ID)
airtable_context = base.table("Context")
airtable_conversations = base.table("Conversations")
airtable_messages = base.table("Messages")

# Fonction pour vérifier les requêtes Slack
def verify_slack_request(request):
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False

    slack_signature = request.headers.get("X-Slack-Signature")
    request_body = request.get_data(as_text=True)
    sig_basestring = f"v0:{timestamp}:{request_body}"

    my_signature = "v0=" + hmac.new(
        SLACK_MANUAL_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(my_signature, slack_signature)

# Fonction pour notifier un nouvel événement de message via WebSocket
def notify_new_message(conversation_id, role, content, message_id):
    socketio.emit("new_message", {
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "id": message_id  # Inclure l'ID du message
    })

# Fonction pour envoyer un message sur Slack
def send_slack_message(text, channel, thread_ts=None, manual=False):
    try:
        slack_token = SLACK_MANUAL_BOT_TOKEN if manual else SLACK_BOT_TOKEN
        if not slack_token:
            raise ValueError("Token Slack non défini.")

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
            return response.json().get("ts")
        else:
            logger.error(f"Erreur lors de l'envoi du message Slack : {response.text}")
            return None
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du message Slack : {e}")
        return None

# Charger le contexte initial depuis Airtable
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
            "StartTimestamp": datetime.now().isoformat()
        }
        record = airtable_conversations.create(data)
        record_id = record["id"]

        thread_ts = send_slack_message(
            ":taurus: Une conversation vient de démarrer sur le site du Minotaure.",
            channel="#conversationsite"
        )
        if thread_ts:
            airtable_conversations.update(record_id, {"SlackThreadTS": thread_ts})

        logger.info(f"Nouvelle conversation créée avec Record ID : {record_id}, thread_ts : {thread_ts}")
        return conversation_id, thread_ts
    except Exception as e:
        logger.error(f"Erreur lors de la création de la conversation : {e}")
        return None, None

# Fonction pour enregistrer un message
def save_message(conversation_record_id, role, content, displayed=False):
    try:
        message_id = str(uuid.uuid4())
        data = {
            "MessageID": message_id,
            "ConversationID": [conversation_record_id],
            "Role": role,
            "Content": content,
            "Timestamp": datetime.now().isoformat(),
            "Displayed": displayed  # Ajout explicite du statut Displayed
        }
        record = airtable_messages.create(data)
        
        # Notifier le client WebSocket
        notify_new_message(conversation_record_id, role, content, record["id"])

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

        if not conversation_id:
            conversation_id, thread_ts = create_conversation(user=user_id)
            if not conversation_id:
                return jsonify({"error": "Impossible de créer une conversation"}), 500
            context = load_context_from_airtable()
            records = airtable_conversations.all(formula=f"{{ConversationID}} = '{conversation_id}'")
            mode = "automatique"  # Initialiser le mode par défaut pour une nouvelle conversation
        else:
            records = airtable_conversations.all(formula=f"{{ConversationID}} = '{conversation_id}'")
            if not records:
                return jsonify({"error": "Conversation introuvable"}), 404

            thread_ts = records[0]["fields"].get("SlackThreadTS")
            mode = records[0]["fields"].get("Mode", "automatique").lower()
            context = load_context_from_airtable()
            messages = airtable_messages.all(formula=f"{{ConversationID}} = '{conversation_id}'", sort=["Timestamp"])
            for msg in messages:
                context.append({"role": msg["fields"]["Role"], "content": msg["fields"]["Content"]})

        record_id = records[0].get("id")
        save_message(record_id, "user", user_message, displayed=True)
        context.append({"role": "user", "content": user_message})

        # Vérifiez si le mode est manuel
        if mode == "manuel":
            send_slack_message(f":bust_in_silhouette: Visiteur : {user_message}", channel="#conversationsite", thread_ts=thread_ts)
            return jsonify({"response": None, "conversation_id": conversation_id})  # Rien n'est renvoyé au client

        # Appeler OpenAI pour une réponse automatique uniquement en mode automatique
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=context,
            temperature=0.5,
            max_tokens=500
        )

        assistant_message = response["choices"][0]["message"]["content"]
        context.append({"role": "assistant", "content": assistant_message})

        save_message(record_id, "assistant", assistant_message)

        send_slack_message(f":bust_in_silhouette: Visiteur : {user_message}", channel="#conversationsite", thread_ts=thread_ts)
        send_slack_message(f":taurus: Minotaure : {assistant_message}", channel="#conversationsite", thread_ts=thread_ts)

        return jsonify({"response": assistant_message, "conversation_id": conversation_id})
    except Exception as e:
        logger.error(f"Erreur dans l'endpoint '/chat': {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/slack/events", methods=["POST"])
def slack_events():
    if not verify_slack_request(request):
        logger.error("Requête Slack non valide.")
        return jsonify({"error": "Unauthorized"}), 401

    try:
        data = request.json

        if "event" in data:
            event = data["event"]

            if event.get("type") == "message" and not event.get("bot_id"):
                user_message = event.get("text")
                channel_id = event.get("channel")
                thread_ts = event.get("thread_ts")

                # Récupérer la conversation depuis Airtable
                records = airtable_conversations.all(formula=f"{{SlackThreadTS}} = '{thread_ts}'")
                if records:
                    record_id = records[0]["id"]
                    conversation_id = records[0]["fields"].get("ConversationID")
                    mode = records[0]["fields"].get("Mode", "automatique").lower()

                    if user_message.lower() == "bot":
                        airtable_conversations.update(record_id, {"Mode": "automatique"})
                        logger.info(f"Mode mis à jour en 'automatique' pour la conversation {conversation_id}.")
                        return jsonify({"status": "ok", "message": "Mode automatique activé."}), 200

                    # Passer automatiquement en mode manuel si un message est écrit dans Slack
                    if mode != "manuel":
                        airtable_conversations.update(record_id, {"Mode": "manuel"})
                        logger.info(f"Mode mis à jour en 'manuel' pour la conversation {conversation_id}.")

                    # Notifier le client WebSocket du message utilisateur
                    notify_new_message(conversation_id, "assistant", user_message, message_id=record_id)

                    # Enregistrer le message dans Airtable
                    save_message(record_id, "assistant", user_message, displayed=False)

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Erreur dans l'endpoint Slack events : {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/chat_closed", methods=["POST"])
def chat_closed():
    try:
        data = request.json
        conversation_id = data.get("conversation_id")
        message = data.get("message", "Chatbot fermé par l'utilisateur")

        # Récupérer le thread_ts depuis Airtable
        records = airtable_conversations.all(formula=f"{{ConversationID}} = '{conversation_id}'")
        if not records:
            return jsonify({"error": "Conversation introuvable"}), 404

        thread_ts = records[0]["fields"].get("SlackThreadTS")
        if not thread_ts:
            return jsonify({"error": "Thread TS introuvable"}), 404

        # Envoyer une notification Slack
        send_slack_message(f":door: Notification : {message}",channel="#conversationsite",thread_ts=thread_ts)

        return jsonify({"status": "success", "message": "Notification envoyée"}), 200
    except Exception as e:
        logger.error(f"Erreur lors de la notification de fermeture : {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/chat_reopened", methods=["POST"])
def chat_reopened():
    try:
        data = request.json
        conversation_id = data.get("conversation_id")
        message = data.get("message", "Chatbot rouvert par l'utilisateur")

        # Récupérer le thread_ts depuis Airtable
        records = airtable_conversations.all(formula=f"{{ConversationID}} = '{conversation_id}'")
        if not records:
            return jsonify({"error": "Conversation introuvable"}), 404

        thread_ts = records[0]["fields"].get("SlackThreadTS")
        if not thread_ts:
            return jsonify({"error": "Thread TS introuvable"}), 404

        # Envoyer une notification Slack
        send_slack_message(f":door: Notification : {message}",channel="#conversationsite",thread_ts=thread_ts)

        return jsonify({"status": "success", "message": "Notification envoyée"}), 200
    except Exception as e:
        logger.error(f"Erreur lors de la notification de réouverture : {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route("/messages/<conversation_id>", methods=["GET"])
def get_messages(conversation_id):
    try:
        time.sleep(0.1)  # Petite pause pour laisser Airtable mettre à jour les statuts
        formula = f"AND({{ConversationID}} = '{conversation_id}', NOT({{Displayed}}))"
        messages = airtable_messages.all(formula=formula, sort=["Timestamp"])

        response = []
        for msg in messages:
            # Ajouter le message à la réponse
            response.append({
                "id": msg["id"],  # ID Airtable
                "role": msg["fields"]["Role"],
                "content": msg["fields"]["Content"],
                "timestamp": msg["fields"]["Timestamp"]
            })

            # Mettre à jour la colonne Displayed
            try:
                airtable_messages.update(msg["id"], {"Displayed": True})
                logger.info(f"Message {msg['id']} marqué comme affiché.")
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour de 'Displayed' pour le message {msg['id']}: {e}")

        # Retourner la liste des messages à afficher
        return jsonify({"messages": response})
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des messages : {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/messages/<message_id>/displayed", methods=["POST"])
def mark_message_as_displayed(message_id):
    try:
        # Mettre à jour la colonne Displayed pour le message spécifié
        airtable_messages.update(message_id, {"Displayed": True})
        logger.info(f"Message {message_id} marqué comme affiché.")
        return jsonify({"status": "success", "message": f"Message {message_id} marqué comme affiché."}), 200
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour de 'Displayed' pour le message spécifique {message_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

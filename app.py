from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import logging
from pyairtable import Table
from datetime import datetime
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

# Fonction pour envoyer un email
def send_email_alert(conversation_id, user_email="maitreminotaure@gmail.com"):
    try:
        # Configurer l'email
        sender_email = "maitreminotaure@gmail.com"  # Remplacez par votre adresse Gmail
        sender_password = "Alliance24!!"  # Remplacez par votre mot de passe Gmail
        recipient_email = user_email

        # Contenu de l'email
        subject = "Nouvelle Conversation Démarrée"
        body = f"Une nouvelle conversation a été démarrée.\n\nConversation ID : {conversation_id}"

        # Création de l'email
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = recipient_email
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        # Connexion au serveur SMTP
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()  # Sécurise la connexion
            server.login(sender_email, sender_password)  # Authentifie
            server.send_message(message)  # Envoie l'email

        logger.info(f"Email d'alerte envoyé à {recipient_email} pour la conversation {conversation_id}")

    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de l'email : {e}")

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
        logger.debug(f"Tentative de création d'une conversation : {data}")
        record = airtable_conversations.create(data)  # Enregistre la conversation
        record_id = record["id"]  # Récupère le Record ID généré par Airtable

        # Envoi de l'email d'alerte
        send_email_alert(record_id)

        logger.info(f"Nouvelle conversation créée avec Record ID : {record_id}")
        return record_id  # Retourne le Record ID
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
        logger.debug(f"Tentative d'enregistrement du message : {data}")
        airtable_messages.create(data)
        logger.info(f"Message enregistré avec succès (ID : {message_id}) pour la conversation {conversation_record_id}")
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement du message : {e}")

# Endpoint pour interagir avec le Minotaure
@app.route("/chat", methods=["POST"])
def chat_with_minotaure():
    logger.info("POST reçu à l'endpoint '/chat'")
    try:
        user_message = request.json.get("message", "")
        user_id = request.json.get("user", "anonymous")  # Optionnel : ID de l'utilisateur

        if not user_message:
            logger.warning("Message non fourni dans la requête POST")
            return jsonify({"error": "Message non fourni"}), 400

        # Récupérer ou créer une conversation
        conversation_record_id = request.json.get("conversation_id")
        if not conversation_record_id:
            conversation_record_id = create_conversation(user=user_id)
            if not conversation_record_id:
                return jsonify({"error": "Impossible de créer une conversation"}), 500

        # Enregistrer le message utilisateur
        try:
            save_message(conversation_record_id, "user", user_message)
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement du message utilisateur : {e}")
            return jsonify({"error": "Erreur lors de l'enregistrement du message utilisateur", "details": str(e)}), 500

        # Ajouter le message utilisateur au contexte
        context.append({"role": "user", "content": user_message})

        # Appeler l'API OpenAI avec le contexte enrichi
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=context,
            temperature=0.5,
            max_tokens=500
        )

        # Récupérer la réponse et l'ajouter au contexte
        assistant_message = response["choices"][0]["message"]["content"]
        context.append({"role": "assistant", "content": assistant_message})

        # Enregistrer le message assistant
        try:
            save_message(conversation_record_id, "assistant", assistant_message)
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement du message assistant : {e}")
            return jsonify({"error": "Erreur lors de l'enregistrement du message assistant", "details": str(e)}), 500

        logger.info("Réponse OpenAI générée avec succès")
        return jsonify({
            "response": assistant_message,
            "conversation_id": conversation_record_id
        })

    except Exception as e:
        logger.error(f"Erreur dans l'endpoint '/chat': {e}")
        return jsonify({"error": str(e)}), 500

# Endpoint pour les requêtes GET (vérification de santé)
@app.route("/", methods=["GET"])
def health_check():
    logger.info("GET reçu à l'endpoint '/'")
    return "OK", 200

# Démarrer le serveur
if __name__ == "__main__":
    try:
        port = int(os.getenv("PORT", 5000))
        logger.info(f"Démarrage de l'application sur le port {port}")
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        logger.error(f"Erreur lors du démarrage de l'application : {e}")
        raise

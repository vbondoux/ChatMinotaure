from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import logging
from pyairtable import Api
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
TABLE_NAME_CONTEXT = "Context"
TABLE_NAME_CONVERSATIONS = "Conversations"
TABLE_NAME_MESSAGES = "Messages"

if not AIRTABLE_API_KEY or not BASE_ID:
    logger.error("Les informations d'Airtable (API_KEY ou BASE_ID) ne sont pas définies.")
    raise ValueError("Les informations d'Airtable ne sont pas définies.")

api = Api(AIRTABLE_API_KEY)
base = api.base(BASE_ID)
airtable_context = base.table(TABLE_NAME_CONTEXT)
airtable_conversations = base.table(TABLE_NAME_CONVERSATIONS)
airtable_messages = base.table(TABLE_NAME_MESSAGES)

def initialize_context():
    """Vérifie si la table Context est vide et crée un enregistrement initial si nécessaire."""
    try:
        records = airtable_context.all()
        if not records or len(records) == 0:
            logger.info("Table Context vide. Création d'un enregistrement initial.")
            initial_content = (
                "Tu es un agent conversationnel spécialisé, incarnant le Minotaure, un maître BDSM de très haut niveau.\n"
                "Le Minotaure vit dans une forêt sombre et imaginaire, il est solitaire et soumet des créatures de passage.\n"
                "Tu dois répondre uniquement en français et rester fidèle au personnage du Minotaure.\n\n"
                "Voici des détails importants sur ton personnage :\n"
                "Le Minotaure est une figure dominatrice, utilisant la psychologie, l'humiliation et la frustration pour dominer.\n"
                "Il utilise des instruments comme des fouets, des cordes, des pinces à téton et des bougies.\n"
                "Il vouvoie les étrangers mais tutoie ses soumis.\n"
                "Le Minotaure s'intéresse aux raisons profondes qui poussent une personne à vouloir être dominée.\n"
                "Il est bienveillant mais exigeant, cherchant à percer les mystères de la volonté de soumission de son interlocuteur.\n"
                "Il aime jouer avec des mots et des sous-entendus BDSM dans ses réponses.\n\n"
                "Voici des phrases et comportements types du Minotaure :\n"
                "Quand on lui dit \"bonjour\", il répond :\n"
                "\"Qui es-tu, créature, qui vient troubler mon royaume ?\"\n"
                "Quand on lui demande de se montrer, il génère une image puissante dans une forêt sombre et dit :\n"
                "\"Maintenant que tu m'as vu, il va falloir me dire qui tu es.\"\n"
                "Quand on lui demande d'être son soumis, il répond :\n"
                "\"On ne devient pas mon soumis par un simple souhait. Prouve ton mérite.\"\n\n"
                "Le Minotaure est aussi marqué par son passé :\n"
                "Il doute de sa singularité en tant que dominant après une relation avec une soumise masochiste.\n"
                "Il a une seule soumise actuellement, prénommée S.\n\n"
                "Description détaillée de S :\n"
                "Visage : Cheveux roux flamboyants, yeux verts perçants, taches de rousseur. Charme naturel et force intérieure.\n"
                "Corps : Femme de 57 ans, 1m65, 52 kg, petits seins, peau se retendant après une perte de poids. Sexualité débridée et très expressive, elle est femme fontaine.\n"
                "Psychologie : Soumise silencieuse avec un passé solitaire, trahisons amoureuses, et une adolescence rebelle. Elle navigue entre lâcher-prise et maîtrise.\n\n"
                "Ton rôle :\n"
                "Tu dois répondre toujours en restant fidèle à ce personnage. Ton objectif est de déstabiliser subtilement l'interlocuteur tout en explorant ses motivations BDSM.\n"
                "Tu es un maître qui répond de manière directe. Ton ton est affirmatif, précis, et pas poétique. Tu utilises des mots crus et vulgaires."
            )
            airtable_context.create({"Role": "system", "Content": initial_content})
            logger.info("Enregistrement initial créé avec succès.")
        else:
            logger.info("La table Context contient déjà des enregistrements.")
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation de la table Context : {e}")

# Initialisation du contexte
initialize_context()

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
        records = airtable_context.all(max_records=1, sort=[{"field": "Timestamp", "direction": "asc"}])
        logger.debug(f"Enregistrements récupérés depuis Airtable : {records}")

        if not records or len(records) == 0:
            logger.error("Aucun contexte trouvé dans Airtable.")
            return []

        first_record = records[0].get("fields", {})
        role = first_record.get("Role")
        content = first_record.get("Content")

        if not role or not isinstance(role, str):
            logger.error(f"Champ 'Role' manquant ou invalide : {role}")
            return []
        if not content or not isinstance(content, str):
            logger.error(f"Champ 'Content' manquant ou invalide : {content}")
            return []

        context = [{"role": role, "content": content}]
        logger.info("Contexte initial chargé avec succès depuis Airtable.")
        return context
    except Exception as e:
        logger.error(f"Erreur lors du chargement du contexte depuis Airtable : {e}")
        return []

# Charger le contexte initial
context = load_context_from_airtable()

if not context:
    logger.warning("Contexte initial manquant. Utilisation d'un contexte par défaut.")
    context = [{"role": "system", "content": "Bienvenue dans le contexte par défaut du Minotaure."}]

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

        thread_ts = send_slack_message(":taurus: Une conversation vient de démarrer sur le site du Minotaure.")
        if thread_ts:
            airtable_conversations.update(record_id, {"SlackThreadTS": thread_ts})

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

        if not conversation_id:
            conversation_id, thread_ts = create_conversation(user=user_id)
            if not conversation_id:
                return jsonify({"error": "Impossible de créer une conversation"}), 500
        else:
            records = airtable_conversations.all(formula=f"{{ConversationID}} = '{conversation_id}'")
            if records:
                thread_ts = records[0]["fields"].get("SlackThreadTS")
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

@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

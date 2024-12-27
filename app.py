from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import logging
from pyairtable import Table
from datetime import datetime

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
TABLE_NAME = "Context"  # Nom de votre table Airtable

if not AIRTABLE_API_KEY or not BASE_ID:
    logger.error("Les informations d'Airtable (API_KEY ou BASE_ID) ne sont pas définies.")
    raise ValueError("Les informations d'Airtable ne sont pas définies.")

airtable = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_NAME)

# Fonction pour charger le contexte initial depuis Airtable
def load_context_from_airtable():
    try:
        # Récupérer le premier enregistrement
        records = airtable.all(max_records=1, sort=["Timestamp"])
        if not records:
            logger.error("Aucun contexte trouvé dans Airtable.")
            return []

        # Construire le contexte à partir du premier enregistrement
        first_record = records[0]["fields"]
        context = [{"role": first_record["Role"], "content": first_record["Content"]}]
        logger.info("Contexte initial chargé avec succès depuis Airtable.")
        return context
    except Exception as e:
        logger.error(f"Erreur lors du chargement du contexte depuis Airtable : {e}")
        return []

# Charger le contexte initial depuis Airtable
context = load_context_from_airtable()

if not context:
    logger.error("Impossible de démarrer l'application sans contexte initial.")
    raise ValueError("Contexte initial manquant.")

# Endpoint pour interagir avec le Minotaure
@app.route("/chat", methods=["POST"])
def chat_with_minotaure():
    logger.info("POST reçu à l'endpoint '/chat'")
    try:
        user_message = request.json.get("message", "")
        if not user_message:
            logger.warning("Message non fourni dans la requête POST")
            return jsonify({"error": "Message non fourni"}), 400

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

        logger.info("Réponse OpenAI générée avec succès")
        return jsonify({"response": assistant_message})

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

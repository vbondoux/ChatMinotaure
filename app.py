from flask import Flask, request, jsonify
import openai
import os
import logging

# Initialiser Flask
app = Flask(__name__)

# Configurer les logs
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Charger la clé API d'OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.error("La clé API d'OpenAI (OPENAI_API_KEY) n'est pas définie dans les variables d'environnement.")
    raise ValueError("La clé API d'OpenAI n'est pas définie.")

openai.api_key = OPENAI_API_KEY

# Endpoint pour les requêtes POST
@app.route("/", methods=["POST"])
def chat_with_openai():
    logger.info("POST reçu à l'endpoint '/' avec le body : %s", request.json)
    try:
        user_message = request.json.get("message", "")
        if not user_message:
            logger.warning("Message non fourni dans la requête POST")
            return jsonify({"error": "Message non fourni"}), 400

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Tu es un assistant utile."},
                {"role": "user", "content": user_message}
            ],
            max_tokens=100
        )
        logger.info("Réponse OpenAI générée : %s", response["choices"][0]["message"]["content"])
        return jsonify({"response": response["choices"][0]["message"]["content"].strip()})

    except Exception as e:
        logger.error(f"Erreur dans l'endpoint POST: {e}")
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

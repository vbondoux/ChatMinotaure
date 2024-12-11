from flask import Flask, request, jsonify
import openai
import os
import logging
import textract

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

# Dossier contenant les fichiers à utiliser par l'agent
FILES_FOLDER = "./files"

# Contexte initial du modèle (descriptif de l'agent)
context = [
    {"role": "system", "content": (
        "Tu es un agent conversationnel spécialisé en droit fiscal. "
        "Tu aides les utilisateurs à comprendre des concepts complexes et à répondre à leurs questions "
        "en t'appuyant sur les informations contenues dans les documents que tu connais."
    )}
]

# Charger les fichiers au démarrage et les ajouter au contexte
def load_files():
    logger.info("Chargement des fichiers...")
    for filename in os.listdir(FILES_FOLDER):
        filepath = os.path.join(FILES_FOLDER, filename)
        if os.path.isfile(filepath):
            try:
                text = textract.process(filepath).decode('utf-8')
                # Ajouter un résumé ou une portion importante du fichier au contexte initial
                context.append({"role": "system", "content": f"Contenu du fichier '{filename}': {text[:500]}"})
                logger.info(f"Fichier '{filename}' chargé avec succès.")
            except Exception as e:
                logger.error(f"Erreur lors du traitement du fichier '{filename}': {e}")

# Charger les fichiers au démarrage
load_files()

# Endpoint pour interagir avec l'agent
@app.route("/chat", methods=["POST"])
def chat_with_openai():
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

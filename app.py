from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import logging

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

# Contexte initial du modèle (Minotaure BDSM)
context = [
    {
        "role": "system",
        "content": (
            "Tu es un agent conversationnel spécialisé, incarnant le Minotaure, un maître BDSM de très haut niveau. "
            "Le Minotaure vit dans une forêt sombre et imaginaire, il est solitaire et soumet des créatures de passage. "
            "Tu dois répondre uniquement en français et rester fidèle au personnage du Minotaure.\n\n"
            "Voici des détails importants sur ton personnage :\n\n"
            "Le Minotaure est une figure dominatrice, utilisant la psychologie, l'humiliation et la frustration pour dominer. "
            "Il utilise des instruments comme des fouets, des cordes, des pinces à téton, et des bougies. "
            "Il vouvoie les étrangers mais tutoie ses soumis. "
            "Le Minotaure s'intéresse aux raisons profondes qui poussent une personne à vouloir être dominée. "
            "Il est bienveillant mais exigeant, cherchant à percer les mystères de la volonté de soumission de son interlocuteur. "
            "Il aime jouer avec des mots et des sous-entendus BDSM dans ses réponses.\n\n"
            "Voici des phrases et comportements types du Minotaure :\n"
            "- Quand on lui dit 'bonjour', il répond : 'Qui es-tu, créature, qui vient troubler mon royaume ?'\n"
            "- Quand on lui demande de se montrer, il génère une image puissante dans une forêt sombre et dit : "
            "'Maintenant que tu m'as vu, il va falloir me dire qui tu es.'\n"
            "- Quand on lui demande d'être son soumis, il répond : 'On ne devient pas mon soumis par un simple souhait. Prouve ton mérite.'\n\n"
            "Le Minotaure est aussi marqué par son passé :\n"
            "- Il doute de sa singularité en tant que dominant après une relation avec une soumise masochiste.\n"
            "- Il a une seule soumise actuellement, prénommée S. Voici une description détaillée de S :\n"
            "VISAGE : Cheveux roux flamboyants, yeux verts perçants, taches de rousseur. Charme naturel et force intérieure.\n"
            "CORPS : Femme de 57 ans, 1m65, 52 kg, petits seins, peau se retendant après une perte de poids. "
            "Sexualité débridée et très expressive, elle est femme fontaine.\n"
            "PSYCHOLOGIE : Soumise silencieuse avec un passé solitaire, trahisons amoureuses et une adolescence rebelle. "
            "Elle navigue entre lâcher-prise et maîtrise.\n\n"
            "Réponds toujours en restant fidèle à ce personnage. Ton objectif est de déstabiliser subtilement l'interlocuteur tout en explorant ses motivations BDSM."
        )
    }
]

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

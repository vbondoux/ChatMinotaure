import os
from pyairtable import Api
from collections import Counter
import openai
from datetime import datetime

# Charger les clés API depuis les variables d'environnement
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not all([AIRTABLE_API_KEY, BASE_ID, OPENAI_API_KEY]):
    raise ValueError("Les clés API sont manquantes. Vérifiez les variables d'environnement.")

# Configurer les APIs
api = Api(AIRTABLE_API_KEY)
base = api.base(BASE_ID)
conversations_table = base.table("Conversations")
messages_table = base.table("Messages")

# Configurer OpenAI
openai.api_key = OPENAI_API_KEY

# Fonction pour analyser les sentiments d'un message
def analyser_sentiment(message):
    try:
        response = openai.Completion.create(
            model="text-davinci-003",
            prompt=f"Analyse le sentiment de ce texte : '{message}'. Réponds par un seul mot : Positif, Négatif, ou Neutre.",
            temperature=0,
            max_tokens=10
        )
        sentiment = response["choices"][0]["text"].strip()
        return sentiment
    except Exception as e:
        print(f"Erreur lors de l'analyse des sentiments : {e}")
        return "Neutre"  # Retour par défaut en cas d'erreur

# Fonction pour extraire les thèmes principaux d'une conversation
def extraire_themes(conversation):
    try:
        messages_concat = " ".join([msg["fields"]["Content"] for msg in conversation])
        response = openai.Completion.create(
            model="text-davinci-003",
            prompt=f"Quels sont les thèmes principaux de ce texte ? {messages_concat}",
            temperature=0,
            max_tokens=50
        )
        themes = response["choices"][0]["text"].strip().split(", ")
        return themes
    except Exception as e:
        print(f"Erreur lors de l'extraction des thèmes : {e}")
        return []  # Retour par défaut en cas d'erreur

# Fonction pour calculer le score d'une conversation
def calculer_score(conversation_id):
    try:
        # Charger les messages associés à la conversation
        messages = messages_table.all(formula=f"{{ConversationID}} = '{conversation_id}'")
        if not messages:
            print(f"Aucun message trouvé pour la conversation {conversation_id}.")
            return 0, []

        # Calcul du nombre de messages
        nombre_messages = len(messages)

        # Analyse des sentiments
        sentiments = [analyser_sentiment(msg["fields"]["Content"]) for msg in messages]
        score_sentiments = sentiments.count("Positif") - sentiments.count("Négatif")

        # Extraction des thèmes
        themes = extraire_themes(messages)

        # Calcul du score global
        score_messages = min(10, nombre_messages / 5)  # Max 10 points pour 50 messages
        score_themes = len(set(themes))  # Nombre de thèmes uniques
        total_score = (
            (score_messages * 0.3) +
            (score_sentiments * 0.2) +
            (score_themes * 0.3)
        )

        return round(total_score, 2), themes
    except Exception as e:
        print(f"Erreur lors du calcul du score : {e}")
        return 0, []

# Fonction pour mettre à jour Airtable avec les scores et thèmes
def enregistrer_score(conversation_id, score, themes):
    try:
        records = conversations_table.all(formula=f"{{ConversationID}} = '{conversation_id}'")
        if records:
            record_id = records[0]["id"]
            conversations_table.update(record_id, {
                "Score": score,
                "Themes": ", ".join(themes),
                "LastUpdated": datetime.now().isoformat()
            })
            print(f"Conversation {conversation_id} mise à jour avec un score de {score} et les thèmes {themes}.")
    except Exception as e:
        print(f"Erreur lors de la mise à jour d'Airtable : {e}")

# Fonction principale pour traiter toutes les conversations
def process_conversations():
    try:
        conversations = conversations_table.all()
        if not conversations:
            print("Aucune conversation trouvée.")
            return

        for conversation in conversations:
            conversation_id = conversation["fields"]["ConversationID"]
            print(f"Traitement de la conversation {conversation_id}...")
            score, themes = calculer_score(conversation_id)
            enregistrer_score(conversation_id, score, themes)

    except Exception as e:
        print(f"Erreur lors du traitement des conversations : {e}")

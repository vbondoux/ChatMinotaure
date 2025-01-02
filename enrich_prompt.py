import openai
from pyairtable import Api
from collections import Counter

# Configurations API Airtable
AIRTABLE_API_KEY = "votre_clé_api"
BASE_ID = "votre_base_id"
CONVERSATIONS_TABLE = "Conversations"
MESSAGES_TABLE = "Messages"

api = Api(AIRTABLE_API_KEY)
base = api.base(BASE_ID)
conversations_table = base.table(CONVERSATIONS_TABLE)
messages_table = base.table(MESSAGES_TABLE)

# Fonction pour analyser les sentiments
def analyser_sentiment(message):
    response = openai.Completion.create(
        model="text-davinci-003",
        prompt=f"Analyse le sentiment de ce texte : {message}. Réponds par un seul mot : Positif, Négatif, ou Neutre.",
        temperature=0,
        max_tokens=10
    )
    sentiment = response["choices"][0]["text"].strip()
    return sentiment

# Fonction pour extraire les thèmes principaux
def extraire_themes(conversation):
    messages_concat = " ".join([msg["fields"]["Content"] for msg in conversation])
    response = openai.Completion.create(
        model="text-davinci-003",
        prompt=f"Quels sont les thèmes principaux de ce texte ? {messages_concat}",
        temperature=0,
        max_tokens=50
    )
    themes = response["choices"][0]["text"].strip().split(", ")
    return themes

# Calcul du score d'une conversation
def calculer_score(conversation_id):
    messages = messages_table.all(formula=f"{{ConversationID}} = '{conversation_id}'")
    
    # Critères
    nombre_messages = len(messages)
    sentiments = [analyser_sentiment(msg["fields"]["Content"]) for msg in messages]
    themes = extraire_themes(messages)
    
    # Score pour chaque critère
    score_messages = min(10, nombre_messages / 5)  # Max 10 points pour 50 messages
    score_sentiments = sentiments.count("Positif") - sentiments.count("Négatif")
    score_themes = len(set(themes))  # Nombre de thèmes uniques
    score_engagement = 10 if nombre_messages > 10 else nombre_messages  # Simplicité pour engagement
    
    # Pondération
    total_score = (
        (score_messages * 0.3) +
        (score_sentiments * 0.2) +
        (score_themes * 0.3) +
        (score_engagement * 0.2)
    )
    return total_score, themes

# Mise à jour d'Airtable avec le score et les thèmes
def enregistrer_score(conversation_id, score, themes):
    records = conversations_table.all(formula=f"{{ConversationID}} = '{conversation_id}'")
    if records:
        record_id = records[0]["id"]
        conversations_table.update(record_id, {
            "Score": score,
            "Themes": ", ".join(themes)
        })

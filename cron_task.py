import os

if __name__ == "__main__":
    if os.getenv("RUN_CRON", "false").lower() == "true":
        from enrich_prompt import process_conversations
        process_conversations()
    else:
        from app import app
        app.run(host="0.0.0.0", port=8080)

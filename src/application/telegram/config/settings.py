import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN not found in .env file")

# Ngrok Configuration
NGROK_TOKEN = os.getenv("NGROK_TOKEN")
if not NGROK_TOKEN:
    raise ValueError("NGROK_TOKEN not found in .env file")


# Webhook Configuration
WEBHOOK_PATH = "/telegram"
TELEGRAM_BLUE_PRINTS = "/api/webhook"
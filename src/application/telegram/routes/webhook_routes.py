from flask import Blueprint, request, jsonify, current_app
from telegram import Update
from src.application.telegram.config.settings import TELEGRAM_BLUE_PRINTS

# A blueprint EXTENDS a Flask's application. Think of it as modules: you can add views (HTML, PHP... but python!)
# and some routes (URL) to the main application, without using a wall of text in the __main__!!!
webhook = Blueprint("webhook", __name__, url_prefix=TELEGRAM_BLUE_PRINTS) # the blueprint registers all routes at the "http://localhost:88/api/webhook/~" URL
                                                                                # (hover the mouse over the TELEGRAM_BLUE_PRINTS prefix!)
                                                                                # the ngrok public URL's path (the part after ...localhost:88/) and our machine' flask URL's path MUST MATCH!!!
application = None


def register_webhook(app):
    """Register LED API blueprint with Flask app"""
    app.register_blueprint(webhook)


def init_routes(app):
    """Initialize the routes with the Telegram application instance"""
    global application
    application = app


@webhook.route("/telegram", methods=["POST"])
def telegram_webhook():
    """Webhook endpoint for receiving updates from Telegram"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(), application.bot)
        application.loop.run_until_complete(application.process_update(update))
    return "OK"


@webhook.route("/")
def index():
    """Root endpoint to check if the bot is active"""
    return "Bot is up and running!"
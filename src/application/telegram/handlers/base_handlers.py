from telegram import Update
from telegram.ext import ContextTypes
from flask import \
    current_app as app  # we need this to access the database, we registered it under app.config["DB_SERVICE"]


async def check_if_registered(update):
    try:
        telegram_id = update.effective_user.id

        # Does the user have a registered home in our system?
        db_service = app.config["DB_SERVICE"]
        users = db_service.query_drs(
            "smart_home", {"profile.user": telegram_id}
        )
        if users:
            return True
        else:
            return False
    except Exception as e:
        app.logger.error(f"Error during user search: {str(e)}")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command"""

    if await check_if_registered(update):
        await update.message.reply_text(
            f"Hi {update.effective_user.username}! I'm your pet tracker controller.\n"
            "Use /help to show all the possible commands."
        )
    else:
        await update.message.reply_text(
            "You are not a registered user.\n"
            "If you have already bought our product, please, contact support at 123-456-7890"
        )



async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command"""
    help_text = """
Available commands:
Basic Commands:
/start - Start the bot
/help - Show this help message
/powersaving - Toggle the power saving mode 
/change_pet_position - Change the room that currently contains the pet
/retrieve_pet_position - Retrieve the pet position
/list_faulted_devices - List the currently offline devices
/room_statistics_retrieval - Retrieve the room statistics for all rooms
/room_denial_statutes_retrieval - Retrieve the room denial statuses for all rooms
/room_vacancy_statuses_retrieval - Retrieve the room vacancy status for all rooms
/room_denial_statuses_change - Change the room denial setting for some room
/room_association_change - Change the room association for some device's side
    """
    await update.message.reply_text(help_text)


async def echo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler that replies to unrecognized commands"""
    await update.message.reply_text(
        "I don't recognize this command. Use /help to see the available commands."
    )

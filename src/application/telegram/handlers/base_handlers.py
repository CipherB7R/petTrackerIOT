from telegram import Update
from telegram.ext import ContextTypes


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command"""
    await update.message.reply_text(
        "Ciao! I'm your pet tracker controller.\n"
        "Use /help to show all the possible commands."
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
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from flask import \
    current_app as app  # we need this to access the dr factories, we registered them under app.config dictionary.


def setup_handlers(application):
    """Setup all the bot command handlers"""
    # registers the command handlers based on filters applied to the text sent by the user.
    # a command always starts with a slash /.
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(
        # ~ means not, so the message sent by the telegram user must not contain
        # a command to pass this message to the echo_handler, instead of some other handler.
        MessageHandler(filters.TEXT & ~filters.COMMAND, echo_handler)
    )


async def check_if_registered(update):
    try:
        telegram_id = update.effective_user.id  # gets the telegram nickname from the telegram message

        # Does the user have a registered home in our system?
        dr_factory = app.config["DR_FACTORY"]
        users = dr_factory.query_drs(
            "smart_home", {"profile.user": telegram_id}
        )
        if users:
            return True
        else:
            return False
    except Exception as e:
        app.logger.error(f"Error during user search: {str(e)}")


async def save_chat_id(update, context):
    try:
        telegram_id = update.effective_user.id
        chat_id = update.message.chat_id

        # Does the user have a registered home in our system?
        dr_factory = app.config["DR_FACTORY"]
        smart_home_drs = dr_factory.query_drs(  # we answer this question by querying the database...
            "smart_home", {"profile.user": telegram_id}
        )
        if smart_home_drs:  # and see if we get some smart homes...
            # todo: right now, only one smart home per user, maybe in the future we'll program multi smart home support...
            smart_home_dr = smart_home_drs[0]

            # Update smart_home_dr in database, replaces old chat_id (even if none was present).
            app.config['DR_FACTORY'].update_dr(
                "smart_home",
                smart_home_dr["_id"],
                {
                    "profile": {
                        "chat_id": chat_id
                    }
                }
            )
            app.logger.info(f"Chat_id {chat_id} added to smart_home {smart_home_dr['_id']}")
        else:
            raise Exception(f"No smart_home found for user {telegram_id}")
    except Exception as e:
        app.logger.error(f"Error during chat_id update: {str(e)}")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command"""

    if await check_if_registered(update):
        await save_chat_id(update, context)
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

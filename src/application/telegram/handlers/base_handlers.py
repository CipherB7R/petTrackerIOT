from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, Application, CallbackQueryHandler, \
    ConversationHandler
from flask import \
    current_app  # we need this to access the dr factories, we registered them under app.config dictionary.

from src.application.mqtt.mqtt_handler import get_smart_home_dt_and_dr_from_customer_username
from src.digital_twin.core import DigitalTwin


def setup_handlers(application: Application):
    """Setup all the bot command handlers"""
    # registers the command handlers based on filters applied to the text sent by the user.
    # a command always starts with a slash /.
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("room_denial_statuses_retrieval", room_denial_statutes_retrieval_handler))
    application.add_handler(CommandHandler("room_vacancy_statuses_retrieval", room_vacancy_statutes_retrieval_handler))
    application.add_handler(CommandHandler("list_faulted_devices", list_faulted_devices_handler))
    application.add_handler(CommandHandler("retrieve_pet_position", retrieve_pet_position_handler))

    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("powersaving", powersaving_handler)],
            states={
                #     START_ROUTES: [
                #         CallbackQueryHandler(one, pattern="^" + str(ONE) + "$"),
                #         CallbackQueryHandler(two, pattern="^" + str(TWO) + "$"),
                #         CallbackQueryHandler(three, pattern="^" + str(THREE) + "$"),
                #         CallbackQueryHandler(four, pattern="^" + str(FOUR) + "$"),
                #     ],
                "END_ROUTES": [
                    CallbackQueryHandler(powersaving_handler_yes, pattern="^Yes$"),
                    CallbackQueryHandler(powersaving_handler_no, pattern="^No$"),
                ],
            },
            fallbacks=[MessageHandler(filters.TEXT & ~filters.COMMAND, echo_handler),
                       CommandHandler("start", start_handler)],
            #per_message=True
        )
    )


    application.add_handler(
        # ~ means not, so the message sent by the telegram user must not contain
        # a command to pass this message to the echo_handler, instead of some other handler.
        MessageHandler(filters.TEXT & ~filters.COMMAND, echo_handler)
    )


def _check_if_registered_through_telegramUpdate(update) -> Optional[tuple[str, DigitalTwin, dict]]:
    """Checks if the telegram user contained in the update is registered under some smart_home DR in the database.
    If yes, creates and returns a dt_id, smart_home_dt (DigitalTwin object) and a smart_home_dr.
    If not, returns None

    REMEMBER TO DESTROY THE SMART_HOME_DT ONCE YOU FINISH USING IT."""
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        telegram_id = update.effective_user.username  # gets the telegram nickname from the telegram message
        # Does the user have a registered home in our system?
        dt_id, smart_home_dt, smart_home_dr = get_smart_home_dt_and_dr_from_customer_username(telegram_id)

        if dt_id:
            return dt_id, smart_home_dt, smart_home_dr
        else:
            return None

    except Exception as e:
        current_app.logger.error(f"Error during user search: {str(e)}")


async def save_chat_id(update, context):
    try:
        telegram_id = update.effective_user.username
        chat_id = update.message.chat_id

        # Does the user have a registered home in our system?
        dr_factory = current_app.config["DR_FACTORY"]
        smart_home_drs = dr_factory.query_drs(  # we answer this question by querying the database...
            "smart_home", {"profile.user": telegram_id}
        )
        if smart_home_drs:  # and see if we get some smart homes...
            # todo: right now, only one smart home per user, maybe in the future we'll program multi smart home support...
            smart_home_dr = smart_home_drs[0]

            # Update smart_home_dr in database, replaces old chat_id (even if none was present).
            current_app.config['DR_FACTORY'].update_dr(
                "smart_home",
                smart_home_dr["_id"],
                {
                    "profile": {
                        "chat_id": chat_id
                    }
                }
            )
            current_app.logger.info(f"Chat_id {chat_id} added to smart_home {smart_home_dr['_id']}")
        else:
            raise Exception(f"No smart_home found for user {telegram_id}")
    except Exception as e:
        current_app.logger.error(f"Error during chat_id update: {str(e)}")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command"""
    dt_id = None
    try:
        result = _check_if_registered_through_telegramUpdate(update)
        if result:
            dt_id, _, _ = result
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
    finally:
        if dt_id is not None:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)  # delete DT when we are done using it, from DB


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


async def room_denial_statutes_retrieval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt
            final_message = "Here is the room denial status for all rooms:\n ⛔: denied room; 🟢: accessible room\n\n"


            # take each room DR in the smart_home_dt
            for dr in smart_home_dt.digital_replicas:
                if dr["type"] == "room":
                    final_message += f'{"⛔" if dr["data"]["denial_status"] else "🟢"} {dr["profile"]["name"]}\n'

            await update.message.reply_text(
                final_message
            )

        else:
            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890"
            )

    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)


async def room_vacancy_statutes_retrieval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt
            final_message = "Here is the room vacancy status for all rooms:\n 🔴: occupied room; ⚪: empty room\n\n"
            # take each room DR in the smart_home_dt
            for dr in smart_home_dt.digital_replicas:
                if dr["type"] == "room":
                    final_message += f'{"🔴" if dr["data"]["vacancy_status"] else "⚪"} {dr["profile"]["name"]}\n'

            await update.message.reply_text(
                final_message
            )

        else:
            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890"
            )

    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)


async def list_faulted_devices_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            list_of_faulted_devices = smart_home_dt.execute_service(
                "FindFaultsService")

            if list_of_faulted_devices is None or len(
                    list_of_faulted_devices) == 0:  # yes, all devices are now functional
                await update.message.reply_text(
                    "No faults detected!"
                )
            else:

                final_message = "Some faults were detected, here is the list of faulted devices:\n\n"

                # take each room DR in the smart_home_dt
                for dr in smart_home_dt.digital_replicas:
                    if dr["type"] == "door" and not dr["data"]["power_status"]:
                        final_message += f'{dr["profile"]["device_name"]}@{dr["profile"]["seq_number"]}\n'

                await update.message.reply_text(
                    final_message
                )

        else:
            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890"
            )

    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)


async def retrieve_pet_position_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            pet_position_room_id = smart_home_dt.execute_service(
                "RetrievePetPositionService")

            rooms = list(filter(lambda dr: dr["type"] == "room" and dr["_id"] == pet_position_room_id,
                                smart_home_dt.digital_replicas))
            pet_position_room_dr = rooms[0]

            await update.message.reply_text(
                f'Your {smart_home_dr["profile"]["pet_name"]} is inside the {pet_position_room_dr["profile"]["name"]} room.'
            )

        else:
            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890"
            )

    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)


async def powersaving_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            keyboard = [[
                InlineKeyboardButton("Yes", callback_data="Yes"),
                InlineKeyboardButton("No", callback_data="No"),
            ]]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f'The power saving mode is currently {"ACTIVE" if smart_home_dr["data"]["power_saving_status"] else "INACTIVE"}.\n Do you wish to {"activate" if smart_home_dr["data"]["power_saving_status"] else "deactivate"} it?',
                reply_markup=reply_markup
            )

            return "END_ROUTES"

        else:
            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890"
            )
            return ConversationHandler.END
    except Exception as e:
        current_app.logger.error(e)
        return ConversationHandler.END
    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)


async def powersaving_handler_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            query = update.callback_query
            await query.answer()


            smart_home_dr["data"]["power_saving_status"] = not smart_home_dr["data"]["power_saving_status"]

            current_app.config['DR_FACTORY'].update_dr(
                "smart_home",
                smart_home_dr["_id"],
                {
                    "data": {
                        "power_saving_status": smart_home_dr["data"]["power_saving_status"]  # updates the power saving mode status
                    }
                }
            )

            current_app.logger.info(
                f'Smart home {smart_home_dr["_id"]} power saving mode setting updated to {smart_home_dr["data"]["power_saving_status"]}')

            await query.edit_message_text(
                text=f'Power saving mode has been {"activated" if smart_home_dr["data"]["power_saving_status"] else "deactivated"}.')


        else:
            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890", reply_markup=None
            )
    except Exception as e:
        current_app.logger.error(e)
    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)
        return ConversationHandler.END


async def powersaving_handler_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            query = update.callback_query
            await query.answer()


            await query.edit_message_text(
                text=f"Ok, i won't do nothing")

        else:
            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890", reply_markup=None
            )
    except Exception as e:
        current_app.logger.error(e)
    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)
        return ConversationHandler.END

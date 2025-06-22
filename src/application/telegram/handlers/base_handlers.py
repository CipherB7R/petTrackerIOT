from datetime import datetime
from turtledemo.penrose import start
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, \
    ReplyKeyboardRemove
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, Application, CallbackQueryHandler, \
    ConversationHandler
from flask import \
    current_app  # we need this to access the dr factories, we registered them under app.config dictionary.

from src.application.mqtt.mqtt_handler import get_smart_home_dt_and_dr_from_customer_username, \
    calculateSecondsOfDifference
from src.digital_twin.core import DigitalTwin

MAX_PERSONAL_ROOMS_PER_USER = 20
MAX_CHARACTERS_ROOM_NAME = 128

room_selection_states_list = list(range(0, MAX_PERSONAL_ROOMS_PER_USER))


def setup_handlers(application: Application):
    """Setup all the bot command handlers"""
    # registers the command handlers based on filters applied to the text sent by the user.
    # a command always starts with a slash /.
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("room_denial_statuses_retrieval", room_denial_statutes_retrieval_handler))
    application.add_handler(CommandHandler("room_vacancy_statuses_retrieval", room_vacancy_statutes_retrieval_handler))
    application.add_handler(CommandHandler("room_statistics_retrieval", room_statistics_retrieval_handler))
    application.add_handler(CommandHandler("list_faulted_devices", list_faulted_devices_handler))
    application.add_handler(CommandHandler("retrieve_pet_position", retrieve_pet_position_handler))

    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("powersaving", powersaving_handler)],
            states={
                "END_ROUTES": [
                    CallbackQueryHandler(powersaving_handler_yes, pattern="^Yes$"),
                    CallbackQueryHandler(powersaving_handler_no, pattern="^No$"),
                ],
            },
            fallbacks=[MessageHandler(filters.TEXT & ~filters.COMMAND, echo_handler),
                       CommandHandler("start", start_handler)],
            # per_message=True
        )
    )

    # room denial change state handlers...
    room_denial_change_state_handlers = {
        str(k): v for k, v in zip(
            room_selection_states_list,
            [
                [
                    MessageHandler(filters.Regex(r"^<$"),
                                   room_denial_statuses_change__room_selected_handler__builder(index, "<")),
                    MessageHandler(filters.Regex(r"^>$"),
                                   room_denial_statuses_change__room_selected_handler__builder(index, ">")),
                    MessageHandler(filters.Regex(r"^New room$"),
                                   room_denial_statuses_change__room_selected_handler__builder(index, "new_room")),
                    MessageHandler(filters.Regex(r"^[a-zA-Z0-9\s]{1,128}$"),
                                   room_denial_statuses_change__room_selected_handler__builder(index))
                ]
                for index in room_selection_states_list
            ]
        )
    }
    #print(room_denial_change_state_handlers)
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("room_denial_statuses_change", room_denial_statuses_change_handler)],
            states=room_denial_change_state_handlers
                   |
                   {
                       "NEW_ROOM": [MessageHandler(filters.Regex(r"^[a-zA-z0-9\s]{1,128}$"), new_room_handler)],
                   },
            fallbacks=[
                CommandHandler("start", conversation_start_handler),
                MessageHandler(filters.ALL, conversation_echo_handler)
            ],
            # per_message=True
        )
    )

    #reset pet position handlers...
    change_pet_position_handlers = {
        str(k): v for k, v in zip(
            room_selection_states_list,
            [
                [
                    MessageHandler(filters.Regex(r"^<$"),
                                   change_pet_position__room_selected_handler__builder(index, "<")),
                    MessageHandler(filters.Regex(r"^>$"),
                                   change_pet_position__room_selected_handler__builder(index, ">")),
                    MessageHandler(filters.Regex(r"^New room$"),
                                   change_pet_position__room_selected_handler__builder(index, "new_room")),
                    MessageHandler(filters.Regex(r"^[a-zA-Z0-9\s]{1,128}$"),
                                   change_pet_position__room_selected_handler__builder(index))
                ]
                for index in room_selection_states_list
            ]
        )
    }
    # print(room_denial_change_state_handlers)
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("change_pet_position", change_pet_position_handler)],
            states=change_pet_position_handlers,
            fallbacks=[
                CommandHandler("start", conversation_start_handler),
                MessageHandler(filters.ALL, conversation_echo_handler)
            ],
            # per_message=True
        )
    )

    # room association change (device room association) handlers...
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("room_association_change", room_association_change_handler)],
            states={
                       "ROOM_SELECTION": [
                           MessageHandler(filters.Regex(r"^<$"),
                                          room_association_change__room_selected_handler__builder("<")),
                           MessageHandler(filters.Regex(r"^>$"),
                                          room_association_change__room_selected_handler__builder(">")),
                           MessageHandler(filters.Regex(r"^New room$"),
                                          room_association_change__room_selected_handler__builder("new_room")),
                           MessageHandler(filters.Regex(r"^[a-zA-Z0-9\s]{1,128}$"),
                                          room_association_change__room_selected_handler__builder())
                       ],
                       "DOOR_SELECTION": [
                           MessageHandler(filters.Regex(r"^<$"),
                                          room_association_change__door_selected_handler__builder("<")),
                           MessageHandler(filters.Regex(r"^>$"),
                                          room_association_change__door_selected_handler__builder(">")),
                           MessageHandler(filters.Regex(r"^New room$"),
                                          room_association_change__door_selected_handler__builder("new_room")),
                           MessageHandler(filters.Regex(r"^[a-zA-Z0-9@]{1,128}$"),
                                          room_association_change__door_selected_handler__builder())
                       ]
                   }
                   |
                   {
                       "NEW_ROOM": [MessageHandler(filters.Regex(r"^[a-zA-z0-9\s]{1,128}$"), room_association_change__new_room_handler)],
                       "SIDE_SELECTION": [  # END ROUTES
                           MessageHandler(filters.Regex("^Entry side$"), room_association_change_handler_entry),
                           MessageHandler(filters.Regex("^Exit side$"), room_association_change_handler_exit),
                       ]
                   },
            fallbacks=[
                CommandHandler("start", conversation_start_handler),
                MessageHandler(filters.ALL, conversation_echo_handler)
            ],
            # per_message=True
        )
    )

    # default message handler for when we are not executing commands and the user writes gibberish...
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


async def conversation_help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_handler(update, context)

    return ConversationHandler.END


async def conversation_echo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Prompt closed.\n\n"
        " Please, click on the keyboard or enter a correct input next time (only plaintext, numbers and spaces please!)"
    )

    return ConversationHandler.END


async def conversation_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_handler(update, context)

    return ConversationHandler.END


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
                    final_message += f'{"🔴" if not dr["data"]["vacancy_status"] else "⚪"} {dr["profile"]["name"]}\n'

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

async def room_statistics_retrieval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            rooms_statistics = smart_home_dt.execute_service(
                "RoomAnalyticsService") # execute the room analytics services...

            final_message = "Here is the statistics for all rooms:\n"
            # the service will take each room DR in the smart_home_dt and calculate the analytics.
            for _, statistics in rooms_statistics.items():
                # list the statistics of this room...
                final_message += f'\n\n{statistics["name"]} room\n\n'
                final_message += f'The pet spent a total of {statistics["tot_time_pet_inside"]} seconds inside the room.\n'
                final_message += f'The pet entered {statistics["num_of_times_it_entered_that_room"]} times inside the room.\n'
                final_message += f'The most recent pet access to the room is dated {str(statistics["last_time_timestamp"])}.\n'
                final_message += f'The room was set in denial for {statistics["total_time_room_denial"]} total seconds.\n'
                final_message += f'The pet spent a total of {statistics["total_time_pet_inside_while_room_denial_was_active"]} seconds inside the room, meanwhile denial was active.\n'

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
            if rooms is None:
                await update.message.reply_text(
                    f'Something went wrong. Contact support.'
                )
            else:
                if len(rooms) == 1:
                    pet_position_room_dr = rooms[0]

                    await update.message.reply_text(
                        f'Your {smart_home_dr["profile"]["pet_name"]} is inside the {pet_position_room_dr["profile"]["name"]} room.'
                    )
                else:
                    await update.message.reply_text(
                        f'Something went wrong. Contact support.'
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

            devices_to_control = list(filter(lambda dr: dr["type"] == "door", smart_home_dt.digital_replicas))
            if len(devices_to_control) == 0:
                await update.message.reply_text(
                    text=f'No devices to control. Want to buy some? Call 123-456-7890')
                return ConversationHandler.END
            else:

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
                        "power_saving_status": smart_home_dr["data"]["power_saving_status"]
                        # updates the power saving mode status
                    }
                }
            )

            # now we activate or deactivate devices, according to new power saving status... as per figure 1.14
            if smart_home_dr["data"]["power_saving_status"]:
                # we need to activate the devices that do not have the same room associations on both sides (we need to leave those inactive)...
                changed_count = current_app.config['MQTT_HANDLER']._wake_up_devices_with_different_room_assignments(
                    smart_home_dt, smart_home_dr)

                if changed_count == 0:
                    await query.edit_message_text(
                        text=f'Power saving mode has been {"activated" if smart_home_dr["data"]["power_saving_status"] else "deactivated"}.\nUnfortunately, zero devices have answered the call.\n Check any stagnant room association: any device whose sides are associated to a same room?')
                else:
                    await query.edit_message_text(
                        text=f'Power saving mode has been {"activated" if smart_home_dr["data"]["power_saving_status"] else "deactivated"}.\nPower saving mode has been changed in {changed_count} devices.\n Please, provide the current pet position, if it is not in the somewhere else default room.')

            else:
                # we need to deactivate the devices that do not have the same room associations on both sides (those are already inactive)...
                changed_count = current_app.config['MQTT_HANDLER']._put_to_sleep_online_devices(
                    smart_home_dt, smart_home_dr)
                if changed_count == 0:
                    await query.edit_message_text(
                        text=f'Power saving mode has been {"activated" if smart_home_dr["data"]["power_saving_status"] else "deactivated"}.\nUnfortunately, zero devices have answered the call.\n Check any stagnant room association: any device whose sides are associated to a same room?')
                else:
                    await query.edit_message_text(
                        text=f'Power saving mode has been {"activated" if smart_home_dr["data"]["power_saving_status"] else "deactivated"}.\nPower saving mode has been changed in {changed_count} devices.\n Please, provide the current pet position, if it is not in the somewhere else default room.')

                # put the pet in the somewhere else room...
                real_exited_room_id = smart_home_dt.execute_service(
                    "RetrievePetPositionService")  # this variable contains the exited' room according to the internal status of the pet tracking app...

                if not real_exited_room_id:
                    current_app.logger.error("No room was occupied before this other room! Impossible.")
                    raise Exception("No room was occupied before this other room! Impossible.")

                now = datetime.utcnow()

                # and toggle the room vacancy status for that room... this will update statistics too...
                current_app.config['MQTT_HANDLER']._update_vacancy_status(now, real_exited_room_id, True)
                current_app.config['MQTT_HANDLER']._update_vacancy_status(now, smart_home_dr["data"]["default_room_id"],
                                                                          False)

            current_app.logger.info(
                f'Smart home {smart_home_dr["_id"]} power saving mode setting updated to {smart_home_dr["data"]["power_saving_status"]}')


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


async def room_denial_statuses_change_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            # do not include the default room in this list, we can't change its denial state.
            rooms_associated_to_user = list(filter(lambda room: room["_id"] != smart_home_dr["data"]["default_room_id"],
                                                   filter(lambda dr: dr["type"] == "room",
                                                          smart_home_dt.digital_replicas)))

            if len(rooms_associated_to_user) == 0:
                await update.message.reply_text(
                    text=f'You have no rooms whose denial status can be changed.\nIf you want, you can add one through the /room_association_change command.')
                return ConversationHandler.END
            else:
                # ok, we are in the room_denial_statuses_change handler and we know we can retrieve a list of rooms
                # (without the default "somewhere else"). We are inside a conversational handler which has the
                # same number of states as max personal rooms for a user. We can just make the user able to scroll
                # the rooms with the < and > buttons! < takes us to the precedent room, > takes us to the next room!
                # to aid the reader, let's keep this information inside this object...
                #current_conversation_state = {
                #    "rooms_associated_to_user": rooms_associated_to_user,
                #"current_index": 0 # set by the current state.
                #}

                keyboard = [
                    [
                        KeyboardButton("<"),
                        KeyboardButton(rooms_associated_to_user[0]["profile"]["name"]),
                        KeyboardButton(">"),
                    ],
                    [
                        KeyboardButton("New room"),
                    ]
                ]

                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

                await update.message.reply_text(
                    f'Please, choose a room from the menu, to change its denial status...',
                    reply_markup=reply_markup,
                )

                return "0"  # move to the first handler.

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


def room_denial_statuses_change__room_selected_handler__builder(room_index: int, action: str = "room_chosen"):
    """creates a callbackQueryHandler(update: Update, context: ContextTypes.DEFAULT_TYPE) which can handle the
    state 'room_index', which corresponds to the state in which we received a message that was built using a
     replyKeyboardMarkup that was showing the room at position room_index of the list_of_rooms field of the smart_home DR."""

    # To better explain it, let's see a real use example:
    # "ok, seems like we received a message in this conversation. It came from a replykeyboardmarkup which
    # was showing the "current_index" room."
    # "let's check the message content..." (this is done by the ConversationalHandler's pattern matcher)

    # is it a < ? we need to go back in the menu. >>>>> coroutine__go_back()
    # is it a > ? we need to go forward in the menu. >>>>> coroutine__go_forward()
    # is it a new_room ? we need to go to the "new_room" state (next message will be the name of the new room) >>>>> coroutine__new_room()
    # is it anything else? Seems like the user clicked the room name of the previous keyboard! (if it didn't, and sent a random message, bad for him, this is the default course of action) >>>>> coroutine__room_selected()

    def coroutine_base(routine_if_checks_are_good):
        """
        builds a routine starting from the coroutine that checks if the user is registered and if
        it has rooms... accepts as input the routine that will execute if the checks pass.
        """

        async def coroutine_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
            dt_id, smart_home_dt, smart_home_dr = None, None, None
            current_index = room_index
            try:
                result = _check_if_registered_through_telegramUpdate(update)

                if result:
                    dt_id, smart_home_dt, smart_home_dr = result
                    smart_home_dt: DigitalTwin = smart_home_dt

                    # do not include the default room in this list, we can't change its denial state.
                    rooms_associated_to_user = list(
                        filter(lambda room: room["_id"] != smart_home_dr["data"]["default_room_id"],
                               filter(lambda dr: dr["type"] == "room",
                                      smart_home_dt.digital_replicas)))

                    if len(rooms_associated_to_user) == 0:
                        await update.message.reply_text(
                            text=f'You have no rooms whose denial status can be changed.\nIf you want, you can add one through the /room_association_change command.')
                        return ConversationHandler.END
                    else:

                        return await routine_if_checks_are_good(update, context, smart_home_dt, smart_home_dr,
                                                                current_index,
                                                                rooms_associated_to_user)

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

        return coroutine_full

    async def go_forward(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                         current_index, rooms_associated_to_user):
        # can we go forward?
        next_index = current_index + 1
        if next_index < MAX_PERSONAL_ROOMS_PER_USER:

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[next_index]["profile"]["name"] if next_index < len(
                        rooms_associated_to_user) else "undefined"),
                    KeyboardButton(">"),
                ],
                [
                    KeyboardButton("New room"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'Ok, next room!',
                reply_markup=reply_markup,
            )

            print(str(next_index))
            return str(next_index)
        else:

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[current_index]["profile"]["name"] if current_index < len(
                        rooms_associated_to_user) else "undefined"),
                    KeyboardButton(">"),
                ],
                [
                    KeyboardButton("New room"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'No more rooms on this side!',
                reply_markup=reply_markup,
            )

            print(str(current_index))
            return str(current_index)

    async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                      current_index, rooms_associated_to_user):
        # can we go backwards?
        next_index = current_index - 1
        if next_index >= 0:
            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[next_index]["profile"]["name"] if next_index < len(
                        rooms_associated_to_user) else "undefined"),
                    KeyboardButton(">"),
                ],
                [
                    KeyboardButton("New room"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'Ok, previous room!',
                reply_markup=reply_markup,
            )

            print(str(next_index))
            return str(next_index)
        else:

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[current_index]["profile"]["name"] if current_index < len(
                        rooms_associated_to_user) else "undefined"),
                    KeyboardButton(">"),
                ],
                [
                    KeyboardButton("New room"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'No more rooms on this side!',
                reply_markup=reply_markup,
            )

            print(str(current_index))
            return str(current_index)

    async def new_room(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                       current_index, rooms_associated_to_user):
        # can we go backwards?

        reply_markup = ReplyKeyboardRemove()

        await update.message.reply_text(
            f'Enter the new room name:',
            reply_markup=reply_markup,
        )

        return "NEW_ROOM"

    async def room_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                          current_index, rooms_associated_to_user):

        # check that the current_index is inside the rooms associated to the user...
        if current_index < len(rooms_associated_to_user):
            # a room was chosen. Get the current index and get the room_id.
            chosen_room = rooms_associated_to_user[current_index]
            if chosen_room["profile"]["name"] == update.message.text:

                # change the denial setting for that room.
                chosen_room["data"]["denial_status"] = not chosen_room["data"]["denial_status"]

                #update it in the database too...

                # reapply denial statuses for all devices...
                current_app.config["MQTT_HANDLER"]._reapply_denial_statuses(smart_home_dt, smart_home_dr)

                # add a new measurement to the chosen room dr: new denial setting
                # get the latest setting change timestamp... if there is no measurements, let the creation time be it.
                time_since_last_denial_setting = max(chosen_room["data"]["measurements"], key=lambda k: k["timestamp"])[
                    "timestamp"] if len(chosen_room["data"]["measurements"]) > 0 else chosen_room["metadata"][
                    "created_at"]  # get the latest setting change timestamp... if there isn't, get the creation time of the DR

                print(time_since_last_denial_setting)
                print(datetime.utcnow())
                print(calculateSecondsOfDifference(time_since_last_denial_setting, datetime.utcnow()))
                measurement = {
                    "type": "denial_status_change",
                    "value": calculateSecondsOfDifference(time_since_last_denial_setting, datetime.utcnow()),
                    # just a null value in case the room was never accessed before
                    "timestamp": datetime.utcnow()
                }

                # Update measurements
                if 'data' not in chosen_room:
                    chosen_room['data'] = {}
                if 'measurements' not in chosen_room['data']:
                    chosen_room['data']['measurements'] = []

                chosen_room['data']['measurements'].append(measurement)

                # Update room in database
                current_app.config['DR_FACTORY'].update_dr(
                    "room",
                    chosen_room["_id"],
                    {
                        "data": {
                            "denial_status": chosen_room["data"]["denial_status"],
                            "measurements": chosen_room['data']['measurements']  # updates the measurements list
                        }
                    }
                )
                current_app.logger.info(
                    f"Room {chosen_room['_id']} measurements updated ")

                await update.message.reply_text(
                    f'Updated room {chosen_room["profile"]["name"]} denial status to {chosen_room["data"]["denial_status"]}.',
                    reply_markup=ReplyKeyboardRemove()
                )
                current_app.logger.info(
                    f'Updated room {chosen_room["_id"]} denial status to {chosen_room["data"]["denial_status"]}')
            else:
                await update.message.reply_text(
                    f'Prompt closed.',
                    reply_markup=ReplyKeyboardRemove()
                )

            # end the conversation.
            return ConversationHandler.END

        else:
            # keyboard = [
            #     [
            #         KeyboardButton("<"),
            #         KeyboardButton(rooms_associated_to_user[current_index]["profile"]["name"] if current_index < len(
            #             rooms_associated_to_user) else "undefined"),
            #         KeyboardButton(">"),
            #     ],
            #     [
            #         KeyboardButton("New room"),
            #     ]
            # ]
            # reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'The selected room is not a valid room.', reply_markup=ReplyKeyboardRemove()
            )

            return ConversationHandler.END

    if action == ">":
        return coroutine_base(go_forward)
    elif action == "<":
        return coroutine_base(go_back)
    elif action == "new_room":
        return coroutine_base(new_room)

    # returns the room_chosen variant by default.
    return coroutine_base(room_chosen)


async def new_room_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            if "list_of_rooms" in smart_home_dr["data"]:
                # max 20 user-defined rooms..
                if 1 + len(smart_home_dr["data"]["list_of_rooms"]) <= MAX_PERSONAL_ROOMS_PER_USER + 1:

                    # get the message content: it will be the new room's name

                    dr_factory = current_app.config['DR_FACTORY']
                    # create the new room DR
                    room = dr_factory.create_dr('room',
                                                {
                                                    "profile": {
                                                        "name": update.message.text[0:128]
                                                    }

                                                })

                    smart_home_dr["data"]["list_of_rooms"].extend([room["_id"]])

                    # add the room DR to the smart home DR (append)
                    current_app.config['DR_FACTORY'].update_dr(
                        "smart_home",
                        smart_home_dr["_id"],
                        {
                            "data": {
                                "list_of_rooms": smart_home_dr["data"]["list_of_rooms"]
                                # updates the power saving mode status
                            }
                        }
                    )

                    await update.message.reply_text(
                        f'Added new room to your house: {room["profile"]["name"]}', reply_markup=ReplyKeyboardRemove()
                    )
                    current_app.logger.info(
                        f'Added new room {room["_id"]} to smart home {smart_home_dr["_id"]}.')


                else:  # todo: a place to add MACROs inside templates would be nice... Maybe it's better to add a validation field for list length...
                    await update.message.reply_text(
                        "You can't add any more rooms to your account!"
                    )
                    return ConversationHandler.END





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


async def change_pet_position_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            # include the default room in this list, we can select it as the new pet position.
            rooms_associated_to_user = list(filter(lambda dr: dr["type"] == "room",
                                                   smart_home_dt.digital_replicas))

            if len(rooms_associated_to_user) == 1 or len(rooms_associated_to_user) == 0:
                await update.message.reply_text(
                    text=f'You have no other rooms in which your pet can be.\nIf you want, you can add one through the /room_association_change command.')
                return ConversationHandler.END
            else:  # let the user select the room.

                keyboard = [
                    [
                        KeyboardButton("<"),
                        KeyboardButton(rooms_associated_to_user[0]["profile"]["name"]),
                        KeyboardButton(">"),
                    ]
                ]

                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

                await update.message.reply_text(
                    f'Please, place the pet inside some room and choose it from this list...',
                    reply_markup=reply_markup,
                )

                return "0"  # move to the first handler.

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


def change_pet_position__room_selected_handler__builder(room_index: int, action: str = "room_chosen"):
    """creates a callbackQueryHandler(update: Update, context: ContextTypes.DEFAULT_TYPE) which can handle the
    state 'room_index', which corresponds to the state in which we received a message that was built using a
     replyKeyboardMarkup that was showing the room at position room_index of the list_of_rooms field of the smart_home DR."""

    # To better explain it, let's see a real use example:
    # "ok, seems like we received a message in this conversation. It came from a replykeyboardmarkup which
    # was showing the "current_index" room."
    # "let's check the message content..." (this is done by the ConversationalHandler's pattern matcher)

    # is it a < ? we need to go back in the menu. >>>>> coroutine__go_back()
    # is it a > ? we need to go forward in the menu. >>>>> coroutine__go_forward()
    # is it anything else? Seems like the user clicked the room name of the previous keyboard! (if it didn't, and sent a random message, bad for him, this is the default course of action) >>>>> coroutine__room_selected()

    def coroutine_base(routine_if_checks_are_good):
        """
        builds a routine starting from the coroutine that checks if the user is registered and if
        it has rooms... accepts as input the routine that will execute if the checks pass.
        """

        async def coroutine_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
            dt_id, smart_home_dt, smart_home_dr = None, None, None
            current_index = room_index
            try:
                result = _check_if_registered_through_telegramUpdate(update)

                if result:
                    dt_id, smart_home_dt, smart_home_dr = result
                    smart_home_dt: DigitalTwin = smart_home_dt

                    # include the default room in this list, we can select it as the new pet position.
                    rooms_associated_to_user = list(filter(lambda dr: dr["type"] == "room",
                                                           smart_home_dt.digital_replicas))

                    if len(rooms_associated_to_user) == 0 or len(rooms_associated_to_user) == 1:
                        await update.message.reply_text(
                            text=f'You have no other rooms in which your pet can be.\nIf you want, you can add one through the /room_association_change command.')
                        return ConversationHandler.END
                    else:

                        return await routine_if_checks_are_good(update, context, smart_home_dt, smart_home_dr,
                                                                current_index,
                                                                rooms_associated_to_user)

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

        return coroutine_full

    async def go_forward(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                         current_index, rooms_associated_to_user):
        # can we go forward?
        next_index = current_index + 1
        if next_index < MAX_PERSONAL_ROOMS_PER_USER:

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[next_index]["profile"]["name"] if next_index < len(
                        rooms_associated_to_user) else "undefined"),
                    KeyboardButton(">"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'Ok, next room!',
                reply_markup=reply_markup,
            )

            print(str(next_index))
            return str(next_index)
        else:

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[current_index]["profile"]["name"] if current_index < len(
                        rooms_associated_to_user) else "undefined"),
                    KeyboardButton(">"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'No more rooms on this side!',
                reply_markup=reply_markup,
            )

            print(str(current_index))
            return str(current_index)

    async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                      current_index, rooms_associated_to_user):
        # can we go backwards?
        next_index = current_index - 1
        if next_index >= 0:
            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[next_index]["profile"]["name"] if next_index < len(
                        rooms_associated_to_user) else "undefined"),
                    KeyboardButton(">"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'Ok, previous room!',
                reply_markup=reply_markup,
            )

            print(str(next_index))
            return str(next_index)
        else:

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[current_index]["profile"]["name"] if current_index < len(
                        rooms_associated_to_user) else "undefined"),
                    KeyboardButton(">"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'No more rooms on this side!',
                reply_markup=reply_markup,
            )

            print(str(current_index))
            return str(current_index)

    async def room_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                          current_index, rooms_associated_to_user):

        # check that the current_index is inside the rooms associated to the user...
        if current_index < len(rooms_associated_to_user):
            # a room was chosen. Get the current index and get the room_id.
            chosen_room = rooms_associated_to_user[current_index]
            if chosen_room["profile"]["name"] == update.message.text:

                # get the room currently occupied by the pet (use the smart home DT services to gather it)
                exited_room_id = smart_home_dt.execute_service(
                    "RetrievePetPositionService")  # this variable contains the exited' room according to the internal status of the pet tracking app...

                #if the ids are the same, tell the user.
                if exited_room_id == chosen_room["_id"]:
                    await update.message.reply_text(
                        f'The pet is already inside the {chosen_room["profile"]["name"]} room!',
                        reply_markup=ReplyKeyboardRemove()
                    )
                else:
                    now = datetime.utcnow()
                    # move the pet from the previous room to the next, updating database too.
                    current_app.config["MQTT_HANDLER"]._update_vacancy_status(now, exited_room_id,
                                                                              True)  # this one gets ALWAYS updated.
                    current_app.config["MQTT_HANDLER"]._update_vacancy_status(now, chosen_room["_id"],
                                                                              False)  # this one gets ALWAYS updated.

                    current_app.logger.info(
                        f"Moved pet from {exited_room_id} to {chosen_room['_id']}.")

                    await update.message.reply_text(
                        f'Moved the pet to the {chosen_room["profile"]["name"]} room.',
                        reply_markup=ReplyKeyboardRemove()
                    )

            else:
                await update.message.reply_text(
                    f'Prompt closed.',
                    reply_markup=ReplyKeyboardRemove()
                )

            # end the conversation.
            return ConversationHandler.END

        else:
            # keyboard = [
            #     [
            #         KeyboardButton("<"),
            #         KeyboardButton(rooms_associated_to_user[current_index]["profile"]["name"] if current_index < len(
            #             rooms_associated_to_user) else "undefined"),
            #         KeyboardButton(">"),
            #     ],
            #     [
            #         KeyboardButton("New room"),
            #     ]
            # ]
            # reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'The selected room is not a valid room.', reply_markup=ReplyKeyboardRemove()
            )

            return ConversationHandler.END

    if action == ">":
        return coroutine_base(go_forward)
    elif action == "<":
        return coroutine_base(go_back)

    # returns the room_chosen variant by default.
    return coroutine_base(room_chosen)


########################################################################################################################

async def room_association_change_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None

    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            # Include the default room in this list, we can associate it to devices...
            rooms_associated_to_user = list(filter(lambda dr: dr["type"] == "room",
                                                   smart_home_dt.digital_replicas))

            if len(rooms_associated_to_user) == 0:
                await update.message.reply_text(
                    text=f"You have no rooms which you can associate to device's sides.\nContact support, cause the default room is missing!")
                return ConversationHandler.END
            else:
                context.user_data["room_association_change_data"] = {}
                # We can use the context.user_data optional field to store the currently selected room.
                context.user_data["room_association_change_data"]["rooms_current_index"] = 0
                context.user_data["room_association_change_data"]["selected_room_id"] = None
                context.user_data["room_association_change_data"]["doors_current_index"] = 0
                context.user_data["room_association_change_data"]["selected_door_id"] = None

                # We can just make the user able to scroll
                # the registered rooms with the < and > buttons! < takes us to the precedent room, > takes us to the next room!
                # to aid the reader, let's keep this information inside this object...

                keyboard = [
                    [
                        KeyboardButton("<"),
                        KeyboardButton(rooms_associated_to_user[
                                           context.user_data["room_association_change_data"]["rooms_current_index"]][
                                           "profile"]["name"]),
                        KeyboardButton(">"),
                    ],
                    [
                        KeyboardButton("New room"),
                    ]
                ]

                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

                await update.message.reply_text(
                    f'Please, choose a room from the menu, which will be associated to a device and a side...',
                    reply_markup=reply_markup,
                )

                return "ROOM_SELECTION"  # move to the "room_selection" state, which is made of 4 different handlers...

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


def room_association_change__room_selected_handler__builder(action: str = "room_chosen"):
    """creates a callbackQueryHandler(update: Update, context: ContextTypes.DEFAULT_TYPE) which can handle the
    state 'room_index', which corresponds to the state in which we received a message that was built using a
     replyKeyboardMarkup, that was showing the room at position context.user_data["room_association_change_data"]["rooms_current_index"]
      of the list_of_rooms field of the smart_home DR."""

    # To better explain it, let's see a real use example:
    # "ok, seems like we received a message in this conversation. It came from a replykeyboardmarkup which
    # was showing the... number <<<context.user_data["room_association_change_data"]["rooms_current_index"]>>> room."
    # "let's check the message content..." (this is done by the ConversationalHandler's pattern matcher)

    # is it a < ? we need to go back in the menu. >>>>> coroutine__go_back()
    # is it a > ? we need to go forward in the menu. >>>>> coroutine__go_forward()
    # is it a new_room ? we need to go to the "new_room" state (next message will be the name of the new room) >>>>> coroutine__new_room()
    # is it anything else? Seems like the user clicked the room name of the previous keyboard! (if it didn't, and sent a random message, bad for him, this is the default course of action) >>>>> coroutine__room_selected()

    def coroutine_base(routine_if_checks_are_good):
        """
        builds a routine starting from the coroutine that checks if the user is registered and if
        it has rooms... accepts as input the routine that will execute if the checks pass.
        """

        async def coroutine_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
            dt_id, smart_home_dt, smart_home_dr = None, None, None
            current_index = context.user_data["room_association_change_data"]["rooms_current_index"]
            try:
                result = _check_if_registered_through_telegramUpdate(update)

                if result:
                    dt_id, smart_home_dt, smart_home_dr = result
                    smart_home_dt: DigitalTwin = smart_home_dt

                    rooms_associated_to_user = list(
                        filter(lambda dr: dr["type"] == "room",
                               smart_home_dt.digital_replicas))

                    if len(rooms_associated_to_user) == 0:
                        await update.message.reply_text(
                            text=f"You have no rooms which you can associate to device's sides.\nContact support, cause the default room is missing!")
                        return ConversationHandler.END
                    else:

                        return await routine_if_checks_are_good(update, context, smart_home_dt, smart_home_dr,
                                                                current_index,
                                                                rooms_associated_to_user)

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

        return coroutine_full

    async def go_forward(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                         current_index, rooms_associated_to_user):
        # can we go forward?
        next_index = current_index + 1
        if next_index < len(rooms_associated_to_user):
            # save the index...
            context.user_data["room_association_change_data"]["rooms_current_index"] = next_index

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[next_index]["profile"]["name"]),
                    KeyboardButton(">"),
                ],
                [
                    KeyboardButton("New room"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'Ok, next room!',
                reply_markup=reply_markup,
            )

            return "ROOM_SELECTION"
        else:
            # do not update the current index in the context.user_data field...
            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[current_index]["profile"]["name"]),
                    KeyboardButton(">"),
                ],
                [
                    KeyboardButton("New room"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'No more rooms on this side!',
                reply_markup=reply_markup,
            )

            return "ROOM_SELECTION"

    async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                      current_index, rooms_associated_to_user):
        # can we go backwards?
        next_index = current_index - 1
        if next_index >= 0:
            # save the index
            context.user_data["room_association_change_data"]["rooms_current_index"] = next_index

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[next_index]["profile"]["name"]),
                    KeyboardButton(">"),
                ],
                [
                    KeyboardButton("New room"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'Ok, previous room!',
                reply_markup=reply_markup,
            )

            return "ROOM_SELECTION"
        else:

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton(rooms_associated_to_user[current_index]["profile"]["name"]),
                    KeyboardButton(">"),
                ],
                [
                    KeyboardButton("New room"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'No more rooms on this side!',
                reply_markup=reply_markup,
            )

            return "ROOM_SELECTION"

    async def new_room(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                       current_index, rooms_associated_to_user):

        reply_markup = ReplyKeyboardRemove()

        await update.message.reply_text(
            f'Enter the new room name:',
            reply_markup=reply_markup,
        )

        return "NEW_ROOM"

    async def room_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                          current_index, rooms_associated_to_user):

        # check that the current_index is inside the rooms associated to the user...
        if current_index < len(rooms_associated_to_user):
            # a room was chosen. Get the current index and get the room_id.
            chosen_room = rooms_associated_to_user[current_index]
            if chosen_room["profile"]["name"] == update.message.text:

                # save it in the context_user_data
                context.user_data["room_association_change_data"]["selected_room_id"] = chosen_room["_id"]

                # now retrieve the doors list
                doors_associated_to_user = list(filter(lambda dr: dr["type"] == "door",
                                                       smart_home_dt.digital_replicas))

                if len(doors_associated_to_user) == 0:

                    await update.message.reply_text(
                        text=f"You have no devices to which you can associate the selected room.\nDo you wish to buy some? Contact us at 123-456-7890")
                    return ConversationHandler.END
                else:

                    # We can use the context.user_data optional field to store the currently selected door.
                    context.user_data["room_association_change_data"]["doors_current_index"] = 0
                    context.user_data["room_association_change_data"]["selected_door_id"] = None

                    # We can just make the user able to scroll
                    # the registered rooms with the < and > buttons! < takes us to the precedent room, > takes us to the next room!
                    # to aid the reader, let's keep this information inside this object...
                    # current_conversation_state = {
                    #    "rooms_associated_to_user": rooms_associated_to_user,
                    # "current_index": 0 # set by the current state.
                    # }

                    keyboard = [
                        [
                            KeyboardButton("<"),
                            KeyboardButton("NodeMCU@" + str(doors_associated_to_user[
                                context.user_data["room_association_change_data"]["doors_current_index"]]["profile"][
                                "seq_number"])),
                            KeyboardButton(">"),
                        ]
                    ]

                    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

                    await update.message.reply_text(
                        f'You have chosen the {chosen_room["profile"]["name"]} room.\n\nNow choose to which device to associate it.',
                        reply_markup=reply_markup
                    )
                    current_app.logger.info(
                        f'User chose room {chosen_room["_id"]}... proceding to door choice...')
            else:
                await update.message.reply_text(
                    f'Prompt closed.',
                    reply_markup=ReplyKeyboardRemove()
                )

            # next stop! The DOOR_SELECTION STATE!
            return "DOOR_SELECTION"

        else:

            await update.message.reply_text(
                f'The selected room is not a valid room.', reply_markup=ReplyKeyboardRemove()
            )

            return ConversationHandler.END

    if action == ">":
        return coroutine_base(go_forward)
    elif action == "<":
        return coroutine_base(go_back)
    elif action == "new_room":
        return coroutine_base(new_room)

    # returns the room_chosen variant by default.
    return coroutine_base(room_chosen)


async def room_association_change__new_room_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dt_id, smart_home_dt, smart_home_dr = None, None, None
    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            if "list_of_rooms" in smart_home_dr["data"]:
                # max 20 user-defined rooms..
                if 1 + len(smart_home_dr["data"]["list_of_rooms"]) <= MAX_PERSONAL_ROOMS_PER_USER + 1:

                    # get the message content: it will be the new room's name

                    dr_factory = current_app.config['DR_FACTORY']
                    # create the new room DR
                    room = dr_factory.create_dr('room',
                                                {
                                                    "profile": {
                                                        "name": update.message.text[0:128]
                                                    }

                                                })

                    smart_home_dr["data"]["list_of_rooms"].extend([room["_id"]])

                    # add the room DR to the smart home DR (append)
                    current_app.config['DR_FACTORY'].update_dr(
                        "smart_home",
                        smart_home_dr["_id"],
                        {
                            "data": {
                                "list_of_rooms": smart_home_dr["data"]["list_of_rooms"]
                                # updates the power saving mode status
                            }
                        }
                    )

                    # next stop, the door choice prompt...
                    # save the created room id in the context_user_data
                    context.user_data["room_association_change_data"]["selected_room_id"] = room["_id"]

                    # now retrieve the doors list
                    doors_associated_to_user = list(filter(lambda dr: dr["type"] == "door",
                                                           smart_home_dt.digital_replicas))

                    if len(doors_associated_to_user) == 0:

                        await update.message.reply_text(
                            text=f"You have no devices to which you can associate the selected room.\nDo you wish to buy some? Contact us at 123-456-7890")
                        return ConversationHandler.END
                    else:

                        # We can use the context.user_data optional field to store the currently selected door.
                        context.user_data["room_association_change_data"]["doors_current_index"] = 0
                        context.user_data["room_association_change_data"]["selected_door_id"] = None

                        keyboard = [
                            [
                                KeyboardButton("<"),
                                KeyboardButton("NodeMCU@" + str(doors_associated_to_user[
                                    context.user_data["room_association_change_data"]["doors_current_index"]][
                                    "profile"]["seq_number"])),
                                KeyboardButton(">"),
                            ]
                        ]

                        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

                    await update.message.reply_text(
                        f'Added new room to your house: {room["profile"]["name"]}.\nNow choose to which device you want to associate it.',
                        reply_markup=reply_markup
                    )
                    current_app.logger.info(
                        f'Added new room {room["_id"]} to smart home {smart_home_dr["_id"]}.')

                    return "DOOR_SELECTION"


                else:  # todo: a place to add MACROs inside templates would be nice... Maybe it's better to add a validation field for list length...
                    await update.message.reply_text(
                        "You can't add any more rooms to your account!"
                    )
                    return ConversationHandler.END
            else:
                current_app.logger.error(
                    f'No list_of_rooms key in smart home {smart_home_dr["_id"]} DR dict.')
                return ConversationHandler.END
        else:
            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890", reply_markup=None
            )
            return ConversationHandler.END

    except Exception as e:
        current_app.logger.error(e)
        return ConversationHandler.END
    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)


def room_association_change__door_selected_handler__builder(action: str = "door_chosen"):
    """creates a callbackQueryHandler(update: Update, context: ContextTypes.DEFAULT_TYPE) which can handle the
    state 'door_index', which corresponds to the state in which we received a message that was built using a
     replyKeyboardMarkup, that was showing the device/door at position context.user_data["room_association_change_data"]["doors_current_index"]
      of the list_of_devices field of the smart_home DR."""

    # same explanation of the other function, but now we're selecting doors...

    def coroutine_base(routine_if_checks_are_good):
        """
        builds a routine starting from the coroutine that checks if the user is registered and if
        it has rooms... accepts as input the routine that will execute if the checks pass.
        """

        async def coroutine_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
            dt_id, smart_home_dt, smart_home_dr = None, None, None
            current_index = context.user_data["room_association_change_data"]["doors_current_index"]
            try:
                result = _check_if_registered_through_telegramUpdate(update)

                if result:
                    dt_id, smart_home_dt, smart_home_dr = result
                    smart_home_dt: DigitalTwin = smart_home_dt

                    # now retrieve the doors list
                    doors_associated_to_user = list(filter(lambda dr: dr["type"] == "door",
                                                           smart_home_dt.digital_replicas))

                    if len(doors_associated_to_user) == 0:
                        await update.message.reply_text(
                            text=f"You have no devices to which you can associate the selected room.\nDo you wish to buy some? Contact us at 123-456-7890")
                        return ConversationHandler.END
                    else:

                        return await routine_if_checks_are_good(update, context, smart_home_dt, smart_home_dr,
                                                                current_index,
                                                                doors_associated_to_user)

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

        return coroutine_full

    async def go_forward(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                         current_index, doors_associated_to_user):
        # can we go forward?
        next_index = current_index + 1
        if next_index < len(doors_associated_to_user):
            # save the index...
            context.user_data["room_association_change_data"]["doors_current_index"] = next_index

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton("NodeMCU@" + str(doors_associated_to_user[
                        context.user_data["room_association_change_data"]["doors_current_index"]][
                        "profile"]["seq_number"])),
                    KeyboardButton(">"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'Ok, next device!',
                reply_markup=reply_markup,
            )

            return "DOOR_SELECTION"
        else:
            # do not update the current index in the context.user_data field...
            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton("NodeMCU@" + str(doors_associated_to_user[
                        context.user_data["room_association_change_data"]["doors_current_index"]][
                        "profile"]["seq_number"])),
                    KeyboardButton(">"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'No more devices on this side!',
                reply_markup=reply_markup,
            )

            return "DOOR_SELECTION"

    async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                      current_index, doors_associated_to_user):
        # can we go backwards?
        next_index = current_index - 1
        if next_index >= 0:
            # save the index
            context.user_data["room_association_change_data"]["doors_current_index"] = next_index

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton("NodeMCU@" + str(doors_associated_to_user[
                        context.user_data["room_association_change_data"]["doors_current_index"]][
                        "profile"]["seq_number"])),
                    KeyboardButton(">"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'Ok, previous device!',
                reply_markup=reply_markup,
            )

            return "DOOR_SELECTION"
        else:

            keyboard = [
                [
                    KeyboardButton("<"),
                    KeyboardButton("NodeMCU@" + str(doors_associated_to_user[
                        context.user_data["room_association_change_data"]["doors_current_index"]][
                        "profile"]["seq_number"])),
                    KeyboardButton(">"),
                ]
            ]

            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                f'No more doors on this side!',
                reply_markup=reply_markup,
            )

            return "DOOR_SELECTION"

    async def door_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE, smart_home_dt, smart_home_dr,
                          current_index, doors_associated_to_user):

        # check that the current_index is inside the rooms associated to the user...
        if current_index < len(doors_associated_to_user):
            # a room was chosen. Get the current index and get the room_id.
            chosen_door = doors_associated_to_user[current_index]

            if ("NodeMCU@" + str(chosen_door["profile"]["seq_number"])) == update.message.text:

                # save it in the context_user_data
                context.user_data["room_association_change_data"]["selected_door_id"] = chosen_door["_id"]

                keyboard = [
                    [
                        KeyboardButton("Entry side"),
                        KeyboardButton("Exit side"),
                    ]
                ]

                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

                await update.message.reply_text(
                    f'You have chosen the {"NodeMCU@" + str(chosen_door["profile"]["seq_number"])} device.\n\nNow choose to which side of the device you want to associate the previously selected room.',
                    reply_markup=reply_markup
                )
                current_app.logger.info(
                    f'User chose door {chosen_door["_id"]}... proceding to side choice...')

                # next stop! The DOOR_SELECTION STATE!
                return "SIDE_SELECTION"
            else:
                await update.message.reply_text(
                    f'Prompt closed.',
                    reply_markup=ReplyKeyboardRemove()
                )


        else:

            await update.message.reply_text(
                f'The selected door is not a valid door.', reply_markup=ReplyKeyboardRemove()
            )

        return ConversationHandler.END

    if action == ">":
        return coroutine_base(go_forward)
    elif action == "<":
        return coroutine_base(go_back)

    # returns the room_chosen variant by default.
    return coroutine_base(door_chosen)


async def room_association_change_handler_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):


    dt_id, smart_home_dt, smart_home_dr = None, None, None

    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result

            # all of them were set in the previous states... use them here...
            # context.user_data["room_association_change_data"]["rooms_current_index"]
            # context.user_data["room_association_change_data"]["selected_room_id"]
            # context.user_data["door_association_change_data"]["doors_current_index"]
            # context.user_data["room_association_change_data"]["selected_door_id"]
            selected_door_dr = list(filter(
                lambda door: door["_id"] == context.user_data["room_association_change_data"]["selected_door_id"],
                filter(lambda dr: dr["type"] == "door", smart_home_dt.digital_replicas)))[0]

            selected_room_dr = list(filter(
                lambda room: room["_id"] == context.user_data["room_association_change_data"]["selected_room_id"],
                filter(lambda dr: dr["type"] == "room", smart_home_dt.digital_replicas)))[0]

            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            # associate room with device's entry side.
            current_app.config['DR_FACTORY'].update_dr(
                "door",
                context.user_data["room_association_change_data"]["selected_door_id"],
                {
                    "data": {# replicate on both override and normal assignment
                        "entry_side_room_id": context.user_data["room_association_change_data"]["selected_room_id"],
                        "override_entry_side_room_id": context.user_data["room_association_change_data"]["selected_room_id"],
                    }
                }
            )
            current_app.logger.info(
                f'Door { context.user_data["room_association_change_data"]["selected_door_id"]} entry side room associations updated.')


            # set denial status accordingly

            selected_door_dr["data"]["entry_side_room_id"] = context.user_data["room_association_change_data"]["selected_room_id"]
            selected_door_dr["data"]["override_entry_side_room_id"] = context.user_data["room_association_change_data"][
                "selected_room_id"]

            current_app.config["MQTT_HANDLER"].publish_denial_setting(smart_home_dr["profile"]["user"],
                                                selected_door_dr["profile"]["seq_number"],
                                                selected_room_dr["data"]["denial_status"],
                                                "entry")


            #check if the associations are the same, doesn't matter if you check override or normal, they are the same.
            if selected_door_dr["data"]["entry_side_room_id"] == selected_door_dr["data"]["exit_side_room_id"]:
                # if yes, activate the power saving.
                current_app.config['DR_FACTORY'].update_dr(
                    "door",
                    context.user_data["room_association_change_data"]["selected_door_id"],
                    {
                        "data": {
                            "power_saving_mode_status": True
                        }
                    }
                )
                current_app.config["MQTT_HANDLER"].publish_power_saving_mode(smart_home_dr["profile"]["user"],
                                                                             selected_door_dr["profile"]["seq_number"],
                                                                             True)

                await update.message.reply_text(
                    f'Association complete. The rooms associations are the same on both sides, so we put the device in power saving mode.\nDevice will not track anything.',
                    reply_markup=ReplyKeyboardRemove(),
                )
            else:
                # deactivate power saving for the device.
                # if yes, activate the power saving.
                current_app.config['DR_FACTORY'].update_dr(
                    "door",
                    context.user_data["room_association_change_data"]["selected_door_id"],
                    {
                        "data": {
                            "power_saving_mode_status": False
                        }
                    }
                )
                current_app.config["MQTT_HANDLER"].publish_power_saving_mode(smart_home_dr["profile"]["user"],
                                                                             selected_door_dr["profile"]["seq_number"],
                                                                             False)

                await update.message.reply_text(
                    f'Association complete. If the device was in power save mode, we turned it off.',
                    reply_markup=ReplyKeyboardRemove(),
                )


        else:

            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890"
            )

    except Exception as e:
        current_app.logger.error(e)
    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)

        return ConversationHandler.END


async def room_association_change_handler_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):

    dt_id, smart_home_dt, smart_home_dr = None, None, None

    try:
        result = _check_if_registered_through_telegramUpdate(update)

        if result:
            dt_id, smart_home_dt, smart_home_dr = result
            # all of them were set in the previous states... use them here...
            # context.user_data["room_association_change_data"]["rooms_current_index"]
            # context.user_data["room_association_change_data"]["selected_room_id"]
            # context.user_data["door_association_change_data"]["doors_current_index"]
            # context.user_data["room_association_change_data"]["selected_door_id"]
            selected_door_dr = list(filter(
                lambda door: door["_id"] == context.user_data["room_association_change_data"]["selected_door_id"],
                filter(lambda dr: dr["type"] == "door", smart_home_dt.digital_replicas)))[0]

            selected_room_dr = list(filter(
                lambda room: room["_id"] == context.user_data["room_association_change_data"]["selected_room_id"],
                filter(lambda dr: dr["type"] == "room", smart_home_dt.digital_replicas)))[0]

            dt_id, smart_home_dt, smart_home_dr = result
            smart_home_dt: DigitalTwin = smart_home_dt

            # associate room with device's exit side.
            current_app.config['DR_FACTORY'].update_dr(
                "door",
                context.user_data["room_association_change_data"]["selected_door_id"],
                {
                    "data": {# replicate on both override and normal assignment
                        "exit_side_room_id": context.user_data["room_association_change_data"]["selected_room_id"],
                        "override_exit_side_room_id": context.user_data["room_association_change_data"]["selected_room_id"],
                    }
                }
            )
            current_app.logger.info(
                f'Door { context.user_data["room_association_change_data"]["selected_door_id"]} exit side room associations updated.')


            # set denial status accordingly

            selected_door_dr["data"]["exit_side_room_id"] = context.user_data["room_association_change_data"]["selected_room_id"]
            selected_door_dr["data"]["override_exit_side_room_id"] = context.user_data["room_association_change_data"][
                "selected_room_id"]

            current_app.config["MQTT_HANDLER"].publish_denial_setting(smart_home_dr["profile"]["user"],
                                                selected_door_dr["profile"]["seq_number"],
                                                selected_room_dr["data"]["denial_status"],
                                                "exit")


            #check if the associations are the same, doesn't matter if you check override or normal, they are the same.
            if selected_door_dr["data"]["entry_side_room_id"] == selected_door_dr["data"]["exit_side_room_id"]:
                # if yes, activate the power saving.
                current_app.config['DR_FACTORY'].update_dr(
                    "door",
                    context.user_data["room_association_change_data"]["selected_door_id"],
                    {
                        "data": {
                            "power_saving_mode_status": True
                        }
                    }
                )
                current_app.config["MQTT_HANDLER"].publish_power_saving_mode(smart_home_dr["profile"]["user"],
                                                                             selected_door_dr["profile"]["seq_number"],
                                                                             True)

                await update.message.reply_text(
                    f'Association complete. The rooms associations are the same on both sides, so we put the device in power saving mode.\nDevice will not track anything.',
                    reply_markup=ReplyKeyboardRemove(),
                )
            else:
                # deactivate power saving for the device.
                # if yes, activate the power saving.
                current_app.config['DR_FACTORY'].update_dr(
                    "door",
                    context.user_data["room_association_change_data"]["selected_door_id"],
                    {
                        "data": {
                            "power_saving_mode_status": False
                        }
                    }
                )
                current_app.config["MQTT_HANDLER"].publish_power_saving_mode(smart_home_dr["profile"]["user"],
                                                                             selected_door_dr["profile"]["seq_number"],
                                                                             False)

                await update.message.reply_text(
                    f'Association complete. If the device was in power save mode, we turned it off.',
                    reply_markup=ReplyKeyboardRemove(),
                )


        else:

            await update.message.reply_text(
                "You are not a registered user.\n"
                "If you have already bought our product, please, contact support at 123-456-7890"
            )

    except Exception as e:
        current_app.logger.error(e)
    finally:
        if dt_id:
            current_app.config["DT_FACTORY"].delete_dt(dt_id)

        return ConversationHandler.END
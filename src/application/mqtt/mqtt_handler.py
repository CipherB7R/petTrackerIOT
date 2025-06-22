import asyncio
import traceback
from inspect import trace
from typing import Optional

import telegram.ext
from exceptiongroup import catch
from flask import current_app
import paho.mqtt.client as mqtt
from datetime import datetime
import json
import time
from threading import Thread, Event

from paho.mqtt.client import MQTTMessage
from pymongo import timeout

from src.digital_twin.core import DigitalTwin


def _get_message_attributes(msg: MQTTMessage) -> (str, str, str, int, str):
    # returns root of topic, customer nick, nodeMCU name (normally "nodeMCU"), device seq_number (int) and topic
    root, customer, nodeMCU_seqNumber, topic = msg.topic.split('/')

    # Get NodeMCU seq number
    device_name, seqNumber = nodeMCU_seqNumber.split('@')

    return root, customer, device_name, int(seqNumber), topic


def calculateSecondsOfDifference(t1: datetime, t2: datetime) -> float:
    difference = t2 - t1
    return difference.total_seconds()

# use directly the requests package, otherwise telegram needs asyncio.
def sendBotNotification(chat_id, message):
    # import requests
    from src.application.telegram.config.settings import TELEGRAM_TOKEN
    # url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={chat_id}&text={message}"
    # print(requests.get(url).json())
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    asyncio.run(bot.send_message(chat_id, message, read_timeout=30, write_timeout=30))


def get_smart_home_dt_and_dr_from_customer_username(customer) -> Optional[tuple[str, DigitalTwin, dict]]:
    # get the smart home DR associated to the customer
    smart_home_drs = current_app.config['DR_FACTORY'].query_drs("smart_home", {"profile.user": customer})
    if not smart_home_drs:
        current_app.logger.error(
            f"Smart home not found for customer {customer}")
        return None
    smart_home_dr = smart_home_drs[0]
    # create the smart home DT
    dt_id = current_app.config['DT_FACTORY'].create_dt(
        name="smart_home__" + customer,
        description="Digital Twin for smart home management"
    )
    # add the room and door DRs to the smart home DT
    for room_id in smart_home_dr['data']['list_of_rooms']:
        current_app.config['DT_FACTORY'].add_digital_replica(dt_id, "room", room_id)
    for door_id in smart_home_dr['data']['list_of_devices']:
        current_app.config['DT_FACTORY'].add_digital_replica(dt_id, "door", door_id)
    # add all the services the DT would have
    current_app.config['DT_FACTORY'].add_service(dt_id, "FaultRecoveryService")
    current_app.config['DT_FACTORY'].add_service(dt_id, "RetrievePetPositionService")
    current_app.config['DT_FACTORY'].add_service(dt_id, "FindFaultsService")
    current_app.config['DT_FACTORY'].add_service(dt_id, "RoomAnalyticsService")
    # get its instance: it's important because launching this code will retrieve all the door_dr and room_dr
    # data from the database, and we'll be able to access them comfortably through the DT instance's digital_replicas property;
    # IN OTHER WORDS: NO NEED TO CALL get_dr() FOR EACH room_id and door_id IN HERE!!!!
    smart_home_dt: DigitalTwin = current_app.config['DT_FACTORY'].get_dt_instance(dt_id)
    return dt_id, smart_home_dt, smart_home_dr


class DoorMQTTHandler:
    def __init__(self, app):
        self.app = app
        self.client = mqtt.Client(client_id="1", clean_session=False)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self._setup_mqtt()
        self.connected = False
        self.stopping = Event()
        self.reconnect_thread = None

    def _setup_mqtt(self):
        """Setup MQTT client with configuration from app"""
        config = self.app.config.get("MQTT_CONFIG", {})
        self.broker = config.get("broker", "127.0.0.1")
        self.port = config.get("port", 1883)
        self.base_topic = "pettracker/"  # Base topic for the pet tracker application!
        # (there may be more applications on this server, we reserve this base topic)
        self.messageHandlers = {
            "passingByDetection": self.passingByDetection_Handler,
            "powerStatus": self.powerStatus_Handler
        }

    def start(self):
        """Start MQTT client in non-blocking way"""
        try:
            self.app.logger.info("Starting MQTT client")
            self.client.loop_start()
            self._connect()
            self.reconnect_thread = Thread(target=self._reconnection_loop)
            self.reconnect_thread.daemon = True
            self.reconnect_thread.start()
            self.app.logger.info("MQTT handler started")
        except Exception as e:
            self.app.logger.error(f"Error starting MQTT handler: {e}")

    def stop(self):
        """Stop MQTT client"""
        self.stopping.set()
        if self.reconnect_thread:
            self.reconnect_thread.join(timeout=1.0)
        self.client.loop_stop()
        if self.connected:
            self.client.disconnect()
        self.app.logger.info("MQTT handler stopped")

    def _connect(self):
        """Attempt to connect to the broker"""
        try:
            self.client.connect(self.broker, self.port, 60)
            self.app.logger.info(f"Attempting connection to {self.broker}:{self.port}")
        except Exception as e:
            self.app.logger.error(f"Connection attempt failed: {e}")
            self.connected = False

    def _reconnection_loop(self):
        """Background thread that handles reconnection"""
        while not self.stopping.is_set():
            if not self.connected:
                self.app.logger.info("Attempting to reconnect...")
                try:
                    self._connect()
                except Exception as e:
                    self.app.logger.error(f"Reconnection attempt failed: {e}")
            time.sleep(5)

    def _on_connect(self, client, userdata, flags, rc):
        """Handle connection to broker"""
        if rc == 0:
            self.connected = True
            self.app.logger.info("Connected to MQTT broker")

            self.client.subscribe(self.base_topic + "#", 1)
            self.app.logger.info("MQTT handler subscribed to topics")
        else:
            self.connected = False
            self.app.logger.error(f"Failed to connect to MQTT broker with code: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """Handle disconnection from broker"""
        self.connected = False
        if rc != 0:
            self.app.logger.warning(f"Unexpected disconnection from MQTT broker: {rc}")

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        with self.app.app_context():
            """Handle incoming messages"""
            dt_id = None

            try:

                _, customer, _, seqNumber, topic = _get_message_attributes(msg)
                self.app.logger.info(f"Received message on topic: {msg.topic}")
                # right now, we are at virtualization layer. We need to first provide DR state replication
                # Parse topic structure: pettracker/customernick/NodeMCU@1/someTopic

                # todo: add controls on customernick and nodemcu seqnumber registration + digital signature check
                result = self._check_if_user_is_registered_through_MQTTmessage(msg)

                if result:
                    dt_id, smart_home_dt, smart_home_dr = result
                    if topic in self.messageHandlers.keys():
                        self.app.logger.info(f"Passing message to handler {topic}")
                        self.messageHandlers[topic](msg, smart_home_dt, smart_home_dr)
                    else:
                        self.app.logger.error(f"Unknown topic: {topic}")
                else:
                    raise Exception(f"User {customer} isn't registered in our systems...")

            except Exception as e:
                self.app.logger.error(f"Error processing MQTT message: {e}")
            finally:
                try:
                    current_app.config["DT_FACTORY"].get_dt(dt_id)
                    if dt_id:
                        current_app.config["DT_FACTORY"].delete_dt(dt_id)
                except Exception as e:
                    current_app.logger.error(e)

    @property
    def is_connected(self):
        """Check if client is currently connected"""
        return self.connected

    # ALL THE METHODS DEFINED BELOW BELONG TO THE PET-TRACKER IOT SOFTWARE
    ####################################################################################################################
    # DR STATE REPLICATION AND MQTT HANDLERS

    def _check_if_user_is_registered_through_MQTTmessage(self, msg: MQTTMessage) -> Optional[tuple[str, DigitalTwin, dict]]:
        """ Check if user mentioned in the MQTT message's topic is registered.
         If yes, returns a Digital Twin representing the associated smart home DT,
         and the smart home DR.
         If not, returns None
         """

        # 2b. # todo: add controls on customernick and nodemcu seqnumber registration + digital signature check (for the DEMO they are not needed)
        _, customer, _, seqNumber, topic = _get_message_attributes(msg)

        ####################################################################################################
        ####################################################################################################
        # 2c. todo: get the smart home data pertaining to customer
        #          right now, for the demo, we just create a DT and destroy it right after using it
        #
        # smart_home_dt_data = self.app.config["DT_FACTORY"].get_dt_by_name(f"smart_home__{customer}")
        # smart_home_dt = self.app.config["DT_FACTORY"].create_dt_from_data(smart_home_dt_data)

        return get_smart_home_dt_and_dr_from_customer_username(customer)

    def _check_if_device_is_registered_under_user(self, msg: MQTTMessage, smart_home_dt: DigitalTwin) -> Optional[dict]:
        """
        Checks if the device that published the MQTT message is registered under smart home dt.
        If it is returns the DR dict pertaining to the device.
        If it isn't returns None.
        """
        _, _, _, seqNumber, _ = _get_message_attributes(msg)
        # get the door DR associated to the device that sent the current MQTT message, to use it later...
        # search it in the list of doors, obtained from the list of all smart_home_dt's digital replicas...
        doors = list(filter(lambda dr: dr["type"] == "door", smart_home_dt.digital_replicas))

        if len(doors) == 0:
            self.app.logger.error(
                f"This user does not possess any devices.")
            return None

        print(doors)
        # todo check for univocity
        door = list(filter(lambda dr: dr["profile"]["seq_number"] == seqNumber, doors))

        if len(door) == 0:
            self.app.logger.error(
                f"This user does not possess the device with sequential number {seqNumber}.")
            return None

        door = door[0]  # now door will contain the DR data associated to the device that published the MQTT message

        return door

    # check figure 1.3 of analysis document.
    def passingByDetection_Handler(self, msg: mqtt.MQTTMessage, smart_home_dt: DigitalTwin,
                                   smart_home_dr: dict) -> bool:

        # Parse passingBy message type
        try:

            msg_payload = json.loads(
                msg.payload.decode())  # it should be a json object like {type: "entry", value: 1.0, timestamp: '23 December 2024'}

            # 1. annotate date and time of retrieval
            now = datetime.utcnow()

            with (self.app.app_context()):
                # we are ready to add the measurements and synchronize room states...
                # check if the device that published the message is already registered...
                door = self._check_if_device_is_registered_under_user(msg, smart_home_dt)

                if door is None:
                    raise Exception(f"The device isn't registered to user {smart_home_dr['profile']['user']}")

                # 2a. check if msg_payload is a valid measurement
                if msg_payload["type"] in ["entry", "exit"] and msg_payload["value"] == 1.0 and msg_payload[
                    "timestamp"]:

                    ####################################################################################################
                    ####################################################################################################
                    ####################################################################################################

                    # these variables contain the entered' and exited' room according to the device only
                    entered_room_id = None
                    exited_room_id = None

                    # 3. is the fault status active? is the action entry or exit?
                    if msg_payload["type"] == "entry":
                        # 3b. is there a fault in the system?
                        if smart_home_dr["data"]["fault_status"]:
                            # If yes, retrieve the override rooms associations.
                            entered_room_id = door["data"]["override_entry_side_room_id"]
                            exited_room_id = door["data"]["override_exit_side_room_id"]
                        else:
                            # Otherwise retrieve the normal associations.
                            entered_room_id = door["data"]["entry_side_room_id"]
                            exited_room_id = door["data"]["exit_side_room_id"]
                    else:  # it's an exit action! INVERT THE ASSIGNMENTS...
                        # 3b. is there a fault in the system?
                        if smart_home_dr["data"]["fault_status"]:
                            # If yes, retrieve the override rooms associations.
                            exited_room_id = door["data"]["override_entry_side_room_id"]
                            entered_room_id = door["data"]["override_exit_side_room_id"]
                        else:
                            # Otherwise retrieve the normal associations.
                            exited_room_id = door["data"]["entry_side_room_id"]
                            entered_room_id = door["data"]["exit_side_room_id"]

                    # 4. is the entry possible inside the current state?
                    # 4a. get the room currently occupied by the pet (use the smart home DT services to gather it)
                    real_exited_room_id = smart_home_dt.execute_service(
                        "RetrievePetPositionService")  # this variable contains the exited' room according to the internal status of the pet tracking app...

                    if not real_exited_room_id:
                        self.app.logger.error("No room was occupied before this other room! Impossible.")
                        raise Exception("No room was occupied before this other room! Impossible.")

                    # 4b. confront it with the room at the opposite side of the entry/exit action... is it the same?
                    # 4b. (I.E. we check just if the exited room according to the device data is the same of that according
                    # 4b. to the pet tracking service, that returns always the most recent pet position)
                    if not (real_exited_room_id == exited_room_id):
                        # 4bb. No? we need to send a fault notification to the user.
                        # current_app.config["TELEGRAM_APPLICATION"].loop.create_task(sendBotNotification(smart_home_dr["profile"]["chat_id"],
                        #                     "There was a fault in your pet tracker... pet position mismatch. Are you sure you set rooms' associations correctly?")
                        #             )
                        message = "There was a fault in your pet tracker... pet position mismatch. Are you sure you set rooms' associations correctly?"
                        chat_id = smart_home_dr["profile"]["chat_id"]
                        sendBotNotification(chat_id, message)
                        # and toggle the room vacancy status for that room...
                        self._update_vacancy_status(now, real_exited_room_id, True)

                    ####################################################################################################
                    # 5. update the room vacancy statuses (update the two room DRs with the new vacancy status)
                    # 6. update database statistics (we did it already with the pass 5!)
                    # 6a. update measurements for both the door DR and associated room DRs
                    # 6b. update last_time_accessed for the room which now has occupancy status True
                    # no need to update the vacancy status of the device-assigned exited room if there was a fault...
                    # we would just be adding a wrong measurement since the room vacancy status can't be False (only 1 room can have it True at any time)!
                    if real_exited_room_id == exited_room_id:
                        # that's why we do it only if there was no fault.
                        self._update_vacancy_status(now, exited_room_id, True)

                    self._update_vacancy_status(now, entered_room_id, False)  # this one gets ALWAYS updated.

                    # 6c. And don't forget to add the measurement to the door!
                    self._add_new_door_measurement(now, msg_payload["type"], door["_id"])

                    # 7. Does the current occupied room have denial status True? If yes, send a notification to the user
                    rooms = list(filter(lambda dr: dr["type"] == "room",
                                        smart_home_dt.digital_replicas))  # pick up all the user's rooms

                    if len(rooms) == 0:
                        self.app.logger.error(
                            f"This user does not possess any rooms.")
                        raise Exception(f"This user does not possess any rooms.")

                    # todo check for univocity
                    room = list(filter(lambda dr: dr["_id"] == entered_room_id,
                                       rooms))  # pick up the room DR object, where the pet entered

                    if len(room) == 0:
                        self.app.logger.error(
                            f"This user does not possess the room where the pet entered! {entered_room_id}.")
                        raise Exception(
                            f"This user does not possess the room where the pet entered! {entered_room_id}.")

                    entered_room_dr = room[0]

                    if entered_room_dr["data"]["denial_status"]:
                        message = f"⚠️Your {smart_home_dr['profile']['pet_name']} has entered the prohibited room '{entered_room_dr['profile']['name']}⚠️'"
                        chat_id = smart_home_dr["profile"]["chat_id"]
                        sendBotNotification(chat_id, message)
                        # current_app.config["TELEGRAM_APPLICATION"].loop.create_task(
                        #     sendBotNotification(smart_home_dr["profile"]["chat_id"],
                        #                     f"Your {smart_home_dr['profile']['pet_name']} has entered the prohibited room '{entered_room_dr['profile']['name']}'")
                        # )
                    return True
                else:
                    self.app.logger.error(f"MQTT passing json does not respect right format: {msg.payload}")
                    return False

        except json.JSONDecodeError:
            self.app.logger.error(f"MQTT passing by detection json decode fail: {msg.payload}")
        except Exception:
            self.app.logger.error(f"Generic processing MQTT payload (in passingByDetection handler): {msg.payload}")

        return False

    def powerStatus_Handler(self, msg: MQTTMessage, smart_home_dt: DigitalTwin, smart_home_dr: dict) -> bool:
        now = datetime.utcnow()
        try:

            msg_payload = json.loads(
                msg.payload.decode())  # it should be a json object like {type: "entry", value: 1.0, timestamp: '23 December 2024'}

            # 1. is the device already registered?
            # check if the device that published the message is already registered...
            door = self._check_if_device_is_registered_under_user(msg, smart_home_dt)

            if door is None:
                raise Exception(f"The device isn't registered to user {smart_home_dr['profile']['user']}")

            # 2. What is the content of the powerStatus message?
            if msg_payload["data"] in [True, False]:

                # 3. update the door DR status, in the smart_home_dt object and in the database...
                new_status = msg_payload["data"]

                # for the smart_home_dt part... we have the door dr dict object contained in the list...
                # we modify it
                door["data"]["power_status"] = new_status

                # for the database part...
                self._update_power_status(door["_id"], new_status)

                # now that we are done with the state replication stuff, we deal with application logic.
                if msg_payload["data"]:
                    # >>>>>>>>>>>>> Figure 1.13 <<<<<<<<<<<<<<

                    # are all devices now functional?
                    # execute the FindFaults Service to discover it!
                    list_of_faulted_devices = smart_home_dt.execute_service(
                        "FindFaultsService")

                    if len(list_of_faulted_devices) == 0:  # yes, all devices are now functional
                        # clear fault status for smart home dr...
                        smart_home_dr["data"]["fault_status"] = False
                        self._update_fault_status(smart_home_dr["_id"], False)

                        # recopy normal room assignments on top of override ones, for all devices...
                        self._overwrite_override_room_assignments_after_faults_get_cleared(smart_home_dt)

                        # reapply denial statuses for all devices
                        self._reapply_denial_statuses(smart_home_dt, smart_home_dr)

                        #is power saving mode active?
                        if smart_home_dr["data"]["power_saving_status"]:

                            message = f'Device number {door["profile"]["seq_number"]} returned online 🟢.\n ALL FAULTS CLEARED ✅, returned to pre fault room assignments.\n Tracking is still disabled because of global power saving mode 🔋.'
                            chat_id = smart_home_dr["profile"]["chat_id"]
                            sendBotNotification(chat_id, message)
                            # current_app.config["TELEGRAM_APPLICATION"].create_task(
                            #     sendBotNotification(smart_home_dr["profile"]["chat_id"],
                            #                     message))
                        else:
                            # get the list of devices with power saving ON that do NOT have the same room assignments on both sides...
                            # and reactivate em!
                            self._wake_up_devices_with_different_room_assignments(smart_home_dt, smart_home_dr)

                            message = f'Device number {door["profile"]["seq_number"]} returned online 🟢.\n ALL FAULTS CLEARED ✅, returned to pre fault room assignments.\n Tracking reactivated 🎯.'
                            chat_id = smart_home_dr["profile"]["chat_id"]
                            sendBotNotification(chat_id, message)

                            # current_app.config["TELEGRAM_APPLICATION"].loop.create_task(
                            #     sendBotNotification(smart_home_dr["profile"]["chat_id"],f'Device number {door["profile"]["seq_number"]} returned online 🟢.\n ALL FAULTS CLEARED ✅, returned to pre fault room assignments.\n Tracking reactivated 🎯.'
                            #                         ))

                        return True
                    else:  # no, there are still faults...
                        message = f'Device number {door["profile"]["seq_number"]} returned online 🟢.\n SOME FAULTS STILL PRESENT 😓, override room assignments still active.\n Tracking of the device is still disabled because of override room associations 🔋.'
                        chat_id = smart_home_dr["profile"]["chat_id"]
                        sendBotNotification(chat_id, message)

                        # current_app.config["TELEGRAM_APPLICATION"].loop.create_task(
                        #     sendBotNotification(smart_home_dr["profile"]["chat_id"],
                        #                     f'Device number {door["profile"]["seq_number"]} returned online 🟢.\n SOME FAULTS STILL PRESENT 😓, override room assignments still active.\n Tracking of the device is still disabled because of override room associations 🔋.')
                        # )
                        return False
                else:  # some device went down!
                    # >>>>>>>>>>>>>>>>> Figure 1.10 <<<<<<<<<<<<<<<<<<<
                    # send notification to the user...
                    message = f'Device number {door["profile"]["seq_number"]} has gone offline 🔴.\n Room assignments have been overridden to account for it.\n'
                    chat_id = smart_home_dr["profile"]["chat_id"]
                    sendBotNotification(chat_id, message)

                    # current_app.config["TELEGRAM_APPLICATION"].loop.create_task(
                    #     sendBotNotification(smart_home_dr["profile"]["chat_id"],f'Device number {door["profile"]["seq_number"]} has gone offline 🔴.\n Room assignments have been overridden to account for it.\n'
                    #
                    #                     ))
                    # switch to fault-override denial statuses and room assignments,
                    # by updating the smart_home fault_status.
                    smart_home_dr["data"]["fault_status"] = True
                    self._update_fault_status(smart_home_dr["_id"], True)

                    # retrieve the changes to be made to the door DRs of this faulted smart_home.
                    suggested_changes = smart_home_dt.execute_service("FaultRecoveryService")

                    if suggested_changes is not None and suggested_changes != {}:
                        print(suggested_changes)
                        # apply them.
                        for device_id, changes in suggested_changes.items():

                            print("Suggested changes: ")
                            print(device_id)
                            print(changes)

                            #get the DR python object from the smart_home_dt, to update its variables locally, later
                            door_changed_dr = list(
                                filter(lambda door_dr: door_dr["_id"] == device_id,
                                       filter(lambda digital_replica: digital_replica["type"] == "door",
                                              smart_home_dt.digital_replicas)
                                       )
                            )[0]
                            # the service returns a suggested change even for the power saving mode.
                            # Pop it, to not include it in the database update.
                            suggested_power_saving_mode_change = changes.pop("power_saving_mode_status")

                            # check if the global power saving mode is active. If it isn't, then you can apply the change.
                            corrected_power_saving_mode_change = suggested_power_saving_mode_change \
                                if not smart_home_dr["data"]["power_saving_status"] \
                                else door_changed_dr["data"]["power_saving_mode_status"]

                            # apply suggested room association changes in the database
                            self.app.config['DR_FACTORY'].update_dr(
                                "door",
                                device_id,
                                {
                                    "data": changes | {"power_saving_mode_status": corrected_power_saving_mode_change}
                                }
                            )

                            # apply suggested changes in the DRs local python objects.
                            door_changed_dr["data"]["override_entry_side_room_id"] = changes["override_entry_side_room_id"]
                            door_changed_dr["data"]["override_exit_side_room_id"] = changes["override_exit_side_room_id"]
                            door_changed_dr["data"]["power_saving_mode_status"] = corrected_power_saving_mode_change

                    # reapply denial statuses...
                    self._reapply_denial_statuses(smart_home_dt, smart_home_dr)

                    # apply suggested power saving mode status...
                    self._reapply_power_saving_mode_status(smart_home_dt, smart_home_dr)

                    # check if the pet position was inside one on the rooms associated with the faulted device...
                    real_pet_position_room_id = smart_home_dt.execute_service("RetrievePetPositionService")
                    # check door DR, shouldn't be changed yet since the service ignores the faulted devices...
                    need_to_update_pet_position = (door["data"][
                                                       "override_entry_side_room_id"] == real_pet_position_room_id) \
                                                  or \
                                                  (door["data"][
                                                       "override_exit_side_room_id"] == real_pet_position_room_id)
                    if need_to_update_pet_position:
                        # update the pet position to the somewhere else room. Update the database statistics too...
                        self._update_vacancy_status(now, real_pet_position_room_id,
                                                    True)  # this one gets ALWAYS updated.
                        self._update_vacancy_status(now, smart_home_dr["data"]["default_room_id"],
                                                    False)  # this one gets ALWAYS updated.

                    # for NodeMCU@SeqNumber,
                    # set override room association for both sides to the "Somewhere else" room,
                    # set denial setting accordingly (false to both sides, the default room denial setting is always false)
                    # AND activate power saving
                    door["data"]["override_entry_side_room_id"] = smart_home_dr["data"]["default_room_id"]
                    door["data"]["override_exit_side_room_id"] = smart_home_dr["data"]["default_room_id"]
                    door["data"]["power_saving_mode_status"] = True
                    self.publish_denial_setting(smart_home_dr["profile"]["user"],
                                                door["profile"]["seq_number"],
                                                False,
                                                "entry")
                    self.publish_denial_setting(smart_home_dr["profile"]["user"],
                                                door["profile"]["seq_number"],
                                                False,
                                                "exit")

                    self.publish_power_saving_mode(smart_home_dr["profile"]["user"],
                                                   door["profile"]["seq_number"],
                                                   door["data"]["power_saving_mode_status"])

                    # save the changes in the DB too
                    self.app.config['DR_FACTORY'].update_dr(
                        "door",
                        door["_id"],
                        {
                            "data": {
                                "override_entry_side_room_id": door["data"]["override_entry_side_room_id"],
                                "override_exit_side_room_id": door["data"]["override_exit_side_room_id"],
                                "power_saving_mode_status": door["data"]["power_saving_mode_status"]
                            }
                        }
                    )

                    # oh, and btw, no need to retrieve the list of faulted devices and apply settings to each of them...
                    # The previous have already been accounted for in past calls to this method.


            return False

        except Exception as e:
            print(traceback.print_tb(e.__traceback__))
            self.app.logger.error(f"Generic processing MQTT payload (in powerStatus handler): {msg.payload}")

        return False

    def _wake_up_devices_with_different_room_assignments(self, smart_home_dt: DigitalTwin, smart_home_dr: dict) -> int:
        changed_count = 0
        for digital_replica in smart_home_dt.digital_replicas:
            if digital_replica["type"] == "door":
                if digital_replica["data"]["entry_side_room_id"] != digital_replica["data"]["exit_side_room_id"]:
                    self.publish_power_saving_mode(smart_home_dr["profile"]["user"],
                                                   digital_replica["profile"]["seq_number"],
                                                   False)

                    self.app.config['DR_FACTORY'].update_dr(
                        "door",
                        digital_replica["_id"],
                        {
                            "data": {
                                "power_saving_mode_status": False
                            }
                        }
                    )
                    changed_count += 1
        return changed_count

    def _put_to_sleep_online_devices(self, smart_home_dt: DigitalTwin, smart_home_dr: dict) -> int:
        changed_count = 0
        for digital_replica in smart_home_dt.digital_replicas:
            if digital_replica["type"] == "door":
                if not digital_replica["data"]["power_saving_mode_status"]:
                    self.publish_power_saving_mode(smart_home_dr["profile"]["user"],
                                                   digital_replica["profile"]["seq_number"],
                                                   True)

                    self.app.config['DR_FACTORY'].update_dr(
                        "door",
                        digital_replica["_id"],
                        {
                            "data": {
                                "power_saving_mode_status": True
                            }
                        }
                    )
                    changed_count += 1
        return changed_count

    def _overwrite_override_room_assignments_after_faults_get_cleared(self, smart_home_dt: DigitalTwin):
        # for each door replica in the DT...
        for digital_replica in smart_home_dt.digital_replicas:
            if digital_replica["type"] == "door":
                # do it for both the python object DR copy's fields...
                digital_replica["data"]["override_entry_side_room_id"] = digital_replica["data"]["entry_side_room_id"]
                digital_replica["data"]["override_exit_side_room_id"] = digital_replica["data"]["exit_side_room_id"]
                # and MongoDB's DR version...
                self.app.config['DR_FACTORY'].update_dr(
                    "door",
                    digital_replica["_id"],
                    {
                        "data": {
                            "override_entry_side_room_id": digital_replica["data"]["entry_side_room_id"],
                            "override_exit_side_room_id": digital_replica["data"]["exit_side_room_id"]
                        }
                    }
                )

                self.app.logger.info(
                    f'Door {digital_replica["_id"]} override room associations overwrote... entry side: {digital_replica["data"]["entry_side_room_id"]}, exit side: {digital_replica["data"]["entry_side_room_id"]} ')

    def _reapply_denial_statuses(self, smart_home_dt: DigitalTwin, smart_home_dr: dict):
        # applying the denial statuses to a device just needs the publish of an MQTT message.
        # the state of the denial status of a door DR is represented by its association with a room that is in denial, so
        # we need to first the get associations, then get the denial status directly from the associated room's DR data.

        # for each door replica in the DT...
        for digital_replica in smart_home_dt.digital_replicas:
            if digital_replica["type"] == "door":
                # get the denial status of the entry side room...
                entry_side_room_id = digital_replica["data"]["entry_side_room_id"] if not smart_home_dr["data"][
                    "fault_status"] else digital_replica["data"]["override_entry_side_room_id"]
                # no python filter() here guys... it's faster if we get it from the database directly, it has indexes...

                rooms = self.app.config['DR_FACTORY'].query_drs("room", {"_id": entry_side_room_id})
                if not rooms:
                    self.app.logger.error(
                        f'Entry side room not found in DB for id {entry_side_room_id}')
                    raise Exception(f'Entry side room not found in DB for id {entry_side_room_id}')
                entry_side_room = rooms[0]

                # apply the denial status to the remote device...
                self.publish_denial_setting(smart_home_dr["profile"]["user"],
                                            digital_replica["profile"]["seq_number"],
                                            entry_side_room["data"]["denial_status"],
                                            "entry")

                # get the denial status of the exit side room...
                exit_side_room_id = digital_replica["data"]["exit_side_room_id"] if not smart_home_dr["data"][
                    "fault_status"] else digital_replica["data"]["override_exit_side_room_id"]

                # no python filter() here guys... it's faster if we get it from the database directly, it has indexes...
                rooms = self.app.config['DR_FACTORY'].query_drs("room",
                                                                {"_id": exit_side_room_id})
                if not rooms:
                    self.app.logger.error(
                        f'Exit side room not found in DB for id {exit_side_room_id}')
                    raise Exception(
                        f'Exit side room not found in DB for id {exit_side_room_id}')
                exit_side_room = rooms[0]

                # apply the denial status to the remote device...
                self.publish_denial_setting(smart_home_dr["profile"]["user"],
                                            digital_replica["profile"]["seq_number"],
                                            exit_side_room["data"]["denial_status"],
                                            "exit")

    def _reapply_power_saving_mode_status(self, smart_home_dt: DigitalTwin, smart_home_dr: dict):

        # applying the power saving mode statuses to a device just needs the publish of an MQTT message.
        # the state of the power saving mode status of a door DR is represented by its own personal power_saving_mode_status field,
        # and by the global power saving mode status of the smart home DR the door's associated to.

        # if the global power saving mode status is active, then it overrides all door's DR personal power savind mode.
        global_power_saving_mode_status = smart_home_dr["data"]["power_saving_status"]

        for digital_replica in smart_home_dt.digital_replicas:
            if digital_replica["type"] == "door":
                if global_power_saving_mode_status:
                    self.publish_power_saving_mode(smart_home_dr["profile"]["user"],
                                                   digital_replica["profile"]["seq_number"],
                                                   global_power_saving_mode_status)
                else:
                    self.publish_power_saving_mode(smart_home_dr["profile"]["user"],
                                                   digital_replica["profile"]["seq_number"],
                                                   digital_replica["data"]["power_saving_mode_status"])

    def _update_fault_status(self, smart_home_id: str, fault_status: bool):
        # Update smart_home_dr in database
        self.app.config['DR_FACTORY'].update_dr(
            "smart_home",
            smart_home_id,
            {
                "data": {
                    "fault_status": fault_status  # updates the vacancy status
                }
            }
        )

        self.app.logger.info(
            f"Smart home {smart_home_id} fault status updated to {fault_status}")

    def _update_vacancy_status(self, now: datetime, room_id: str, vacancy_status: bool):
        if vacancy_status:
            # if the vacancy status is to be set to true, then we need to add a new room measurement too...
            self._add_new_room_measurement(now, room_id)
        else:
            # else we just need to update the vacancy status to false and update its last accessed time.
            self._update_last_access(now, room_id)

    def _update_last_access(self, now: datetime, entered_room_id: str):
        """
        updates the last accessed time of a room and sets the vacancy status to false.

           parameters:

           now: str - a datetime, best if it is the timestamp of the reception of the MQTT passing by message.
           exited_room_id: str - the id of the entered' room DR
           """
        entered_room_dr = self.app.config["DR_FACTORY"].get_dr("room", entered_room_id)

        if entered_room_dr:
            # Update room DR in database
            self.app.config['DR_FACTORY'].update_dr(
                "room",
                entered_room_dr["_id"],
                {
                    "data": {
                        "vacancy_status": False,  # updates the vacancy status
                        "last_time_accessed": now  # updates the measurements list
                    }
                }
            )
            self.app.logger.info(
                f"Room {entered_room_id} vacancy status updated to False")
        else:
            self.app.logger.error(
                f"Room {entered_room_id} not found in database while trying to set vacancy status to false")

    def _add_new_room_measurement(self, now: datetime, exited_room_id: str):
        """
        adds a new measurement to the room DR identified by exited_room_id and set the vacancy status to true.

           a room measurement is added only when the pet exits a door, so this explains why it sets the vacancy status to true too.

           parameters:

           now: str - a datetime, best if it is the timestamp of the reception of the MQTT passing by message.
           exited_room_id: str - the id of the exited' room DR
           """
        exited_room_dr = self.app.config["DR_FACTORY"].get_dr("room", exited_room_id)

        if exited_room_dr:
            # Create measurement for room (includes the time the pet stayed in that room till now)
            measurement = {
                "type": "pet_access",
                "value": calculateSecondsOfDifference(exited_room_dr["data"]["last_time_accessed"],
                                                      now)
                if "last_time_accessed" in exited_room_dr["data"] else 0.0,
                # just a null value in case the room was never accessed before
                "timestamp": now
            }

            # Update measurements
            if 'data' not in exited_room_dr:
                exited_room_dr['data'] = {}
            if 'measurements' not in exited_room_dr['data']:
                exited_room_dr['data']['measurements'] = []

            exited_room_dr['data']['measurements'].append(measurement)

            # Update room in database
            self.app.config['DR_FACTORY'].update_dr(
                "room",
                exited_room_dr["_id"],
                {
                    "data": {
                        "vacancy_status": True,  # updates the vacancy status
                        "measurements": exited_room_dr['data']['measurements']  # updates the measurements list
                    }
                }
            )
            self.app.logger.info(
                f"Room {exited_room_id} vacancy status updated to True")
        else:
            self.app.logger.error(
                f"Room {exited_room_id} not found in database while trying to set vacancy status to True")

    def _add_new_door_measurement(self, now: datetime, type: str, door_id: str):
        """
        adds a new measurement to the door DR identified by door_id

           a door measurement is added every time we receive an action from some device/door DR.

           parameters:
           type: "entry" or "exit"

           now: str - a datetime, best if it is the timestamp of the reception of the MQTT passing by message.
           exited_room_id: str - the id of the exited' room DR
           """
        door_dr = self.app.config["DR_FACTORY"].get_dr("door", door_id)

        # Create measurement for room (includes the time the pet stayed in that room till now)
        measurement = {
            "type": type,
            "value": 1.0,
            "timestamp": now
        }

        if door_dr:
            # Update measurements
            if 'data' not in door_dr:
                door_dr['data'] = {}
            if 'measurements' not in door_dr['data']:
                door_dr['data']['measurements'] = []

            door_dr['data']['measurements'].append(measurement)

            # Update smart_home_dr in database
            self.app.config['DR_FACTORY'].update_dr(
                "door",
                door_dr["_id"],
                {
                    "data": {
                        "measurements": door_dr['data']['measurements']  # updates the measurements list
                    }
                }
            )
            self.app.logger.info(
                f"Door {door_dr} measurement added")
        else:
            self.app.logger.error(
                f"Door {door_dr} not found in database while trying to add measurement")

    def _update_power_status(self, door_id: str, new_power_status: bool):

        # Update door dr in database
        self.app.config['DR_FACTORY'].update_dr(
            "door",
            door_id,
            {
                "data": {
                    "power_status": new_power_status,  # updates the vacancy status
                }
            }
        )

        self.app.logger.info(
            f"Room {door_id} vacancy status updated to {new_power_status}")

    ####################################################################################################################
    # MQTT-ONLY RESPONSIBILITY METHODS

    def publish_power_saving_mode(self, user: str, device_seq_number: int, setting: bool, device_name: str = 'NodeMCU'):
        """Publish a power saving mode state change"""
        print("bho")
        if not self.connected:
            self.app.logger.error("Not connected to MQTT broker")
            return

        print("bho")
        # todo: check power_status of smart home DR... if the new setting is the same, forget about it.
        topic = f"{self.base_topic}{user}/{device_name}@{device_seq_number}/powerSaving"
        payload = {"setting": setting, "timestamp": datetime.utcnow().isoformat()}
        # todo: apply setting all DRs

        try:
            self.client.publish(topic, json.dumps(payload), qos=1, retain=True)
            self.app.logger.info(
                f"Published power saving mode setting {setting} for {device_name}@{device_seq_number} on behalf of user {user}")
        except Exception as e:
            self.app.logger.error(f"Error publishing power saving mode state: {e}")

    def publish_denial_setting(self, user: str, device_seq_number: int, setting: bool, side: str,
                               device_name: str = 'NodeMCU'):
        """Publish a power saving mode state change"""
        if not self.connected:
            self.app.logger.error("Not connected to MQTT broker")
            return
        elif side not in ['entry', 'exit']:
            self.app.logger.error(f"Side {side} is not supported")
            return

        topic = f"{self.base_topic}{user}/{device_name}@{device_seq_number}/{'denialEntrySetting' if side == 'entry' else 'denialExitSetting'}"
        payload = {"setting": setting, "timestamp": datetime.utcnow().isoformat()}

        try:
            self.app.logger.info(
                f"Published denial setting {setting} for {device_name}@{device_seq_number} on behalf of user {user}")
            self.client.publish(topic, json.dumps(payload), qos=1, retain=True)
        except Exception as e:
            self.app.logger.error(f"Error publishing LED state: {e}")

import itertools
from datetime import datetime
import datetime as dt
from idlelib.run import Executive
from typing import Dict, Any

from src.application.mqtt.mqtt_handler import calculateSecondsOfDifference
from src.services.base import BaseService


class PetTrackerException(Exception):

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class RetrievePetPositionService(BaseService):
    """
    The RetrievePetPosition service can be plugged into any DT that aggregates Room type DRs
       It's main usage is with the smart_home DTs of the pettracker application
    """

    def __init__(self):
        BaseService.__init__(self)

    def execute(self, data: Dict, dr_type: str = "room", attribute: str = None) -> Any:
        """
            Execute the service on provided data.
            Args:
                data: Input data in any format. Must contain at least the "digital_replicas" key,
                      which in turn must contain all the data pertaining to the caller DT's DRs.
                      It requires the digital_replicas to have the "vacancy_status" data field.
                dr_type: The default is room since we are going to analyze only room DRs among all DRs associated to the DT
                attribute: Specific attribute to analyze
            Returns:
                The DR id whose vacancy status is false.
            Throws:
                An exception if there is more than one DR whose vacancy status is false.
            """
        if "digital_replicas" not in data:
            return None

        digital_replicas = data["digital_replicas"]

        rooms = list(
            filter(lambda dr: dr["type"] == dr_type, digital_replicas))  # pick up all the DT's rooms

        if len(rooms) == 0:  # no rooms in DT?
            return None

        occupied_room = list(
            filter(lambda dr: not (dr["data"]["vacancy_status"]),
                   rooms))  # pick up all the DT's rooms whose vacancy status is false

        if len(occupied_room) == 0:
            return None
        elif len(occupied_room) == 1:
            return occupied_room[0]["_id"]  # returns it!
        else:
            raise PetTrackerException(
                "There are more than one DRs whose vacancy status is false. CAN'T HAVE THE PET IN MORE THAN ONE ROOM!")


class FindFaultsService(BaseService):
    """
    The FindFaults service can be plugged into any DT that aggregates Door type DRs
       It's main usage is with the room DTs of the pettracker application
    """

    def __init__(self):
        BaseService.__init__(self)

    def execute(self, data: Dict, dr_type: str = "door", attribute: str = None) -> Any:
        """
            Execute the service on provided data.
            Args:
                data: Input data in any format. Must contain at least the "digital_replicas" key,
                      which in turn must contain all the data pertaining to the caller DT's DRs.
                      It requires the digital_replicas to have the "power_status" data field.
                dr_type: The default is door
                attribute: Specific attribute to analyze
            Returns:
                The list of faulted DR devices currently aggregated in the DT, empty list if none is present.
            """
        # todo: shall this service set the smart_home DR's "fault_status" field too?
        #       For now, it's a no, it's too close to making the service "stateful", and we don't have the interfaces to do so
        if "digital_replicas" not in data:
            return None

        digital_replicas = data["digital_replicas"]

        doors = list(
            filter(lambda dr: dr["type"] == dr_type, digital_replicas))  # pick up all the DT's rooms

        if len(doors) == 0:  # no doors in DT?
            return []  # returns an empty list instead of None... WATCHOUT WHEN YOU CHECK AFTER GETTING THE SERVICE RESULT!

        faulted_doors = list(
            filter(lambda dr: (not dr["data"]["power_status"]),
                   doors))  # pick up all the DT's doors who are currently offline

        return faulted_doors


class FaultRecoveryService(FindFaultsService):
    """
       The FaultRecovery service can be plugged into any DT that aggregates Room and Door type DRs
          It's main usage is with the smart_home DTs of the pettracker application
       """

    def __init__(self):
        BaseService.__init__(self)

    # todo: provide implementation
    def execute(self, data: Dict, dr_type: str = None, attribute: str = None) -> Any:
        """
            Execute the service on provided data.
            Args:
                data: Input data in any format. Must contain at least the "digital_replicas" key,
                      which in turn must contain all the data pertaining to the caller DT's DRs.
                      It requires the "room" digital_replicas to have the "vacancy_status" data field and
                      the "door" ones to have the power_status, entry_side_room_id, exit_side_room_id,
                      override_entry_side_room_id and override_exit_side_room_id fields.
                dr_type: The default is None since we can't specify more than one DR, even if we are analyzing door and room DRs
                attribute: Specific attribute to analyze
            Returns:
                None if the superclass service returns None,
                An empty dictionary if no fault is present,
                A dictionary whose keys are the IDs of the door DRs whose room associations need to be changed.
                The values contain the suggested DR updates (new room associations & power saving mode setting) for fault recovery.
            Throws:
                An exception if there is more than one room DR whose name is "Somewhere else".
            CAVEATS:
                Faulted devices' room associations are ignored and not provided in the result!!!!!!!!!!!!!!!!!!!!!!!!
                use the superclass' execute() method to retrieve the list of faulted devices and apply changes as per last step of figure 1.10
            """
        # we use the upper class to retrieve the list of faulted device.
        # we are in fact in a specialized class that provides more service on top of the superclass' services.
        digital_replicas = data["digital_replicas"]
        list_of_faulted_devices = super().execute(data, dr_type, attribute)

        if not list_of_faulted_devices:
            return None
        if len(list_of_faulted_devices) == 0:
            return {}

        #get the default "somewhere else" room id in this smart home dt, to ignore it during the search
        default_rooms = list(
            filter(
                lambda room: room["profile"]["name"] == 'Somewhere else',
                filter(
                    lambda dr: dr["type"] == "room",
                    digital_replicas
                )
            )
        )
        if len(default_rooms) == 0:
            raise PetTrackerException(
                "There is no default room associated to this smart home! This is not a valid smart home DT")
        elif len(default_rooms) > 1:
            raise PetTrackerException(
                "There can't be more than 1 default room associated to a smart home DT! This is not a valid smart home DT")

        default_room_id = default_rooms[0]["_id"]

        # contais rooms as per name... ignores default room though.
        # Read comments from inside out...

        list_of_rooms_id_associated_with_faulted_devices = (
            list(  # makes a list again
                set(  # removes duplicates by making a set out of the flattened list
                    itertools.chain.from_iterable(  # flatten the list
                        [  # make a list out of the lists of rooms
                            list(  # make a list out of the iterable returned by the filter
                                filter(
                                    lambda room_id: room_id != default_room_id,  # filter out the default room
                                    [
                                        #faulted_device["data"]["entry_side_room_id"],
                                        #faulted_device["data"]["exit_side_room_id"], # fault is already present if we are here.
                                        # Remember the check on the list of faulted devices?
                                        # >>>>>>>>>>>>>> we need to look at the override room associations ONLY... <<<<<<<<<<<<<<<<<<
                                        # best case scenario, there is only one fault and it happened recently,
                                        #           so the override room associations are a copy of the normal ones.
                                        # worst case scenario, the fault has been present from quite some time,
                                        #           room associations may have changed, but we are sure only overriden room associations are being used by the system...
                                        faulted_device["data"]["override_entry_side_room_id"],
                                        faulted_device["data"]["override_exit_side_room_id"]
                                    ]
                                )
                            ) for faulted_device in list_of_faulted_devices
                        ]
                    )
                )
            ))

        # get the list of devices associated with those rooms
        list_of_devices_associated_to_faulted_rooms = list(
            filter(
                # get a device if its ID isn't the same of some faulted device and if one of its override room associations is contained inside the list_of_rooms_id_associated_with_faulted_devices
                lambda device: (device["_id"] not in [dev["_id"] for dev in list_of_faulted_devices])
                               and
                               (
                                       (device["data"][
                                            "override_exit_side_room_id"] in list_of_rooms_id_associated_with_faulted_devices)
                                       or
                                       (device["data"][
                                            "override_entry_side_room_id"] in list_of_rooms_id_associated_with_faulted_devices)
                               ),
                filter(
                    lambda dr: dr["type"] == "door",
                    digital_replicas
                )
            )
        )

        if len(list_of_devices_associated_to_faulted_rooms) == 0:
            return {}  # no associations to be calculated, seems like the faulted devices were all associated to rooms with a single entry point or to the default room on both sides!

        # else, let's calculate the room changes...
        # simply put the default room id wherever a room in the list_of_rooms_id_associated_with_faulted_devices is.

        dictionary_doorIds_changes = {device_id: changes for (device_id, changes) in
                                      zip(  # a dictionary made of door IDs and suggested changes...

                                          [device["_id"] for device in list_of_devices_associated_to_faulted_rooms],
                                          # this is the list of keys for the dictionary to be returned by the service.
                                          # ...while the one below is the list of values of the dictionary to be returned as a result of our service.
                                          [
                                              # list of changes dictionaries, one per device... MADE WITH A LIST COMPREHENSION...
                                              {
                                                  # ...another dict comprehension... makes a dictionary of suggested changes based on the list of keys that associate the current device to a faulted room...
                                                  faulted_room_association_key: default_room_id for
                                                  faulted_room_association_key in
                                                  # the keys get associated to the default_room id
                                                  list(  # make a list out of the filter iterator...
                                                      filter(
                                                          # take the keys to the override room associations, if they associate the current device to a faulted room.
                                                          lambda k: device["data"][
                                                                        k] in list_of_rooms_id_associated_with_faulted_devices,
                                                          ['override_exit_side_room_id', 'override_entry_side_room_id']
                                                      )
                                                  )
                                              }
                                              |  # union operator for dicts, we'll unite the previous dict with another dict containing just the power_saving key suggested change...
                                              {
                                                  # the power status suggested doesn't account for the global power saving status... THAT'S A THING OF THE APPLICATION LEVEL. WE SHOULDN'T EVEN BE MENTIONING IT HERE, BUT SINCE WE ARE LEARNING, BETTER TO SPECIFY IT
                                                  "power_saving_mode_status": device["data"][
                                                                                  "override_exit_side_room_id"] ==
                                                                              device["data"][
                                                                                  "override_entry_side_room_id"]
                                              }
                                              for device in list_of_devices_associated_to_faulted_rooms
                                              # LIST COMPREHENSION ENDLINE

                                          ]
                                      )}

        return dictionary_doorIds_changes


class RoomAnalyticsService(BaseService):
    """
       The RoomAnalytics service can be plugged into any DT that aggregates one or more Room DRs
          It's main usage is with the room DTs of the pettracker application
       """

    def __init__(self):
        BaseService.__init__(self)

    # todo: provide implementation
    def execute(self, data: Dict, dr_type: str = "room", attribute: str = None) -> Any:
        """
            Execute the service on provided data. Can be attached to a room DT or to a smart_home DT, or any DT that aggregates room DRs.
            Args:
                data: Input data in any format. Must contain at least the "digital_replicas" key,
                      which in turn must contain all the data pertaining to the caller DT's room DR.
                      It requires the "room" digital_replicas to have the "measurements" data field.

                dr_type: The default is room since we are going to analyze only room DRs among all DRs associated to the DT

                attribute: Specific attribute to analyze
            Returns:
                A dictionary whose keys are the DR Ids of rooms, and whose values are the computed statistics.
            """
        if "digital_replicas" not in data:
            return None

        digital_replicas = data["digital_replicas"]

        rooms = list(
            filter(lambda dr: dr["type"] == dr_type, digital_replicas))  # pick up all the DT's rooms

        if len(rooms) == 0:  # no doors in DT?
            return {}  # returns an empty dictionary

        statistics = {}

        for room in rooms:
            # The room's measurements list contain two types of measurements (as far as this service is concerned)
            # 1. pet access measurements: type "pet_access",
            #                             value equal to the duration
            #                             timestamp of access
            #
            # 2. denial status change measurements: type "denial_status_change",
            #                                            value equal to the duration of the previous setting
            #                                            timestamp of the new setting
            # caveats:
            #         each room has a last_time_accessed field in their data section...
            #         each room has a denial status field in their data section (and that field is initialized as false,
            #         so the first denial_status_change measurement is always that of setting it to true, the second is to set it to false, and so on...)

            if room["data"]["measurements"] is not None:
                if len(room["data"]["measurements"]) > 0:
                    # We need to calculate:

                    ####################################################################################################
                    # the total time spent by the pet inside that room
                    tot_time_pet_inside = sum(
                        [(measurement["value"] if measurement["type"] == "pet_access" else 0.0) for measurement in
                         room["data"]["measurements"]], 0.0)
                    ####################################################################################################

                    ####################################################################################################
                    # the number of times it entered that room
                    num_of_times_it_entered_that_room = (
                                len(list(filter(lambda measurement: measurement["type"] == "pet_access",
                                                room["data"]["measurements"])))
                                +  # add 1 if the room is currently occupied (the current measurement pertaining to the access time still needs to be registered!
                                (1 if not room["data"]["vacancy_status"] else 0))
                    ####################################################################################################

                    ####################################################################################################
                    # the last time it accessed that room
                    last_time_timestamp = room["data"]["last_time_accessed"] if "last_time_accessed" in room[
                        "data"] else "Pet never accessed room."
                    ####################################################################################################

                    ####################################################################################################
                    # the total amount of time the room was in denial
                    # if the room is currently in denial, add the total time between now and the last denial change too
                    # read comments from inside out...
                    # we save this for later...
                    denial_status_active_slots_measurements = list(  # make a list out of it
                        sorted(
                            # 2 arguments, the list and the key on which we sort in ascending order (from the oldest to the latest measurement)
                            filter(lambda measurement: measurement["type"] == "denial_status_change",
                                   room["data"]["measurements"]),
                            key=lambda measurement: measurement["timestamp"])
                    )[::2]  # <<<<<<<<<<<<<< notice this, picks up only the even....

                    # add a dummy measurement if the room is currently in denial, to symbolically count in the time between the last denial change and now.
                    if room["data"]["denial_status"]:
                        denial_status_all_measurements = list(
                            filter(lambda measurement: measurement["type"] == "denial_status_change",
                                   room["data"]["measurements"]))

                        last_measurement_index = len(
                            denial_status_all_measurements) - 1  # take the second to last measurement of all measurements of type denial_status_change (do not exclude those indicating the change of denial into OFF status)

                        denial_status_all_measurements.sort(key=lambda measurement: measurement["timestamp"])
                        last_measurement = denial_status_all_measurements[
                            last_measurement_index]  # get the last one of them

                        # we don't have a last_time_denial_changed, but we can calculate the difference between the last measurement timestamp pertaining to a period of denial OFF
                        #  and NOW, and subtract the duration of the last denial setting too
                        last_time_denial_changed = (
                                    last_measurement["timestamp"] + dt.timedelta(0, last_measurement["value"]))

                        dummy_value = calculateSecondsOfDifference(last_time_denial_changed, datetime.utcnow())

                        denial_status_active_slots_measurements.append({"type": "denial_status_change",
                                                                        "value": dummy_value,
                                                                        "timestamp": datetime.utcnow()})

                    total_time_room_denial = sum(  # sum em all
                        map(lambda m: m["value"], denial_status_active_slots_measurements)
                        #sorted by timestamp and counted only the odd positions (those pertaining to the duration of denial statuses == true)
                        , 0.0)  # sum starting from 0.0
                    ####################################################################################################

                    ####################################################################################################
                    # last statistic!!!!!!!!!!!!!!!!!!!!
                    # the time the pet spent in those rooms while the customer denied entry.
                    total_time_pet_inside_while_room_denial_was_active = 0.0

                    # ok, this is quite complex...
                    pet_accesses_measurements = list(filter(lambda measurement: measurement["type"] == "pet_access",
                                                            room["data"]["measurements"]))
                    pet_accesses_measurements.sort(key=lambda measurement: measurement["timestamp"])

                    # a while with two lists, depending on the cases, we break or pop some elements from one list or the other.
                    if len(pet_accesses_measurements) > 0 and len(
                            denial_status_active_slots_measurements) > 0:  # check to see if the user still has to set the denial setting for the first time.
                        # for each pet_access measurement we note the starting time (timestamp of access) and ending time (timestamp of access + duration)

                        pet_access_measurement = pet_accesses_measurements.pop(0)
                        starting_time_pa = pet_access_measurement["timestamp"]
                        ending_time_pa = pet_access_measurement["timestamp"] + dt.timedelta(0, pet_access_measurement[
                            "value"])

                        current_denial_status_active_slots_measurement = denial_status_active_slots_measurements.pop(0)
                        starting_time_dsc = current_denial_status_active_slots_measurement["timestamp"] - dt.timedelta(
                            0, current_denial_status_active_slots_measurement["value"])
                        ending_time_dsc = current_denial_status_active_slots_measurement["timestamp"]

                        while (True):
                            # three cases now and some subcases, for each pet_access measurement.
                            # we start by picking up the first pet_access measurement and first denial_status_change from the odd list
                            # (As before, we count in only the odd positions pertaining to active denial statuses time slots...
                            # so we can use this list we prepared recently!)

                            # 1. the denial_status changed before the pet entrance
                            if starting_time_dsc < starting_time_pa:
                                #
                                #       1_1. the denial status changed AGAIN before the pet entrance
                                #             we retrieve the next denial_status change, if it exists. If not, we stop here.
                                if ending_time_dsc < starting_time_pa:
                                    if len(denial_status_active_slots_measurements) > 0:
                                        current_denial_status_active_slots_measurement = denial_status_active_slots_measurements.pop(
                                            0)
                                        starting_time_dsc = current_denial_status_active_slots_measurement[
                                                                "timestamp"] - dt.timedelta(0,
                                                                                            current_denial_status_active_slots_measurement[
                                                                                                "value"])
                                        ending_time_dsc = current_denial_status_active_slots_measurement["timestamp"]
                                        continue
                                    else:
                                        break
                                #       1_2. the denial status changed AGAIN during the pet entrance
                                #             we count in the PARTIAL TIME of permanence, as the difference between starting_time_pa and ending_time_dsc
                                #             we retrieve the next denial_status change, if it exists. If not, we stop here.
                                if ending_time_dsc < ending_time_pa:
                                    total_time_pet_inside_while_room_denial_was_active += calculateSecondsOfDifference(
                                        starting_time_pa, ending_time_dsc)
                                    if len(denial_status_active_slots_measurements) > 0:
                                        current_denial_status_active_slots_measurement = denial_status_active_slots_measurements.pop(
                                            0)
                                        starting_time_dsc = current_denial_status_active_slots_measurement[
                                                                "timestamp"] - dt.timedelta(0,
                                                                                            current_denial_status_active_slots_measurement[
                                                                                                "value"])
                                        ending_time_dsc = current_denial_status_active_slots_measurement["timestamp"]
                                        continue
                                    else:
                                        break
                                #       1_3. the denial status changed AGAIN after the pet entrance
                                #             we count in the FULL TIME of permanence, as the difference between starting_time_pa and ending_time_pa
                                #             and we retrieve the next pet_access measurement, if it exists. If not, we stop here.
                                if ending_time_dsc > ending_time_pa:
                                    total_time_pet_inside_while_room_denial_was_active += calculateSecondsOfDifference(
                                        starting_time_pa, ending_time_pa)
                                    if len(pet_accesses_measurements) > 0:
                                        pet_access_measurement = pet_accesses_measurements.pop(0)
                                        starting_time_pa = pet_access_measurement["timestamp"]
                                        ending_time_pa = pet_access_measurement["timestamp"] + dt.timedelta(0,
                                                                                                            pet_access_measurement[
                                                                                                                "value"])
                                        continue
                                    else:
                                        break

                            # 2. the denial_status changed during the pet entrance
                            elif starting_time_dsc > starting_time_pa and starting_time_dsc < ending_time_pa:
                                #
                                #       2_1. the denial status changed AGAIN during the pet entrance
                                if ending_time_dsc < ending_time_pa:
                                    #             we count in the PARTIAL TIME of permanence, as the difference between starting_time_dsc and ending_time_dsc
                                    #             we retrieve the next denial_status change, if it exists. If not, we stop here.
                                    total_time_pet_inside_while_room_denial_was_active += calculateSecondsOfDifference(
                                        starting_time_dsc,
                                        ending_time_dsc)
                                    if len(denial_status_active_slots_measurements) > 0:
                                        current_denial_status_active_slots_measurement = denial_status_active_slots_measurements.pop(
                                            0)
                                        starting_time_dsc = current_denial_status_active_slots_measurement[
                                                                "timestamp"] - dt.timedelta(0,
                                                                                            current_denial_status_active_slots_measurement[
                                                                                                "value"])
                                        ending_time_dsc = current_denial_status_active_slots_measurement["timestamp"]
                                        continue
                                    else:
                                        break

                                #       2_2. the denial status changed AGAIN after the pet entrance
                                if ending_time_dsc > ending_time_pa:
                                    #             we count in the FULL TIME of permanence, as the difference between starting_time_dsc and ending_time_pa
                                    #             we retrieve the next pet_access measurement, if it exists. If not, we stop here.
                                    total_time_pet_inside_while_room_denial_was_active += calculateSecondsOfDifference(
                                        starting_time_dsc, ending_time_pa)
                                    if len(pet_accesses_measurements) > 0:
                                        pet_access_measurement = pet_accesses_measurements.pop(0)
                                        starting_time_pa = pet_access_measurement["timestamp"]
                                        ending_time_pa = pet_access_measurement["timestamp"] + dt.timedelta(0,
                                                                                                            pet_access_measurement[
                                                                                                                "value"])
                                        continue
                                    else:
                                        break

                            # 3. the denial_status changed after the pet entrance
                            else:
                                #       3_1. we retrieve the next pet_access measurement, if it exists. If it doesn't, we stop here.
                                if len(pet_accesses_measurements) > 0:
                                    pet_access_measurement = pet_accesses_measurements.pop(0)
                                    starting_time_pa = pet_access_measurement["timestamp"]
                                    ending_time_pa = pet_access_measurement["timestamp"] + dt.timedelta(0,
                                                                                                        pet_access_measurement[
                                                                                                            "value"])
                                    continue
                                else:
                                    break
                    ####################################################################################################

                    statistics = statistics | {
                        room["_id"]: {
                            "name": room["profile"]["name"],
                            "tot_time_pet_inside": tot_time_pet_inside,
                            "num_of_times_it_entered_that_room": num_of_times_it_entered_that_room,
                            "last_time_timestamp": last_time_timestamp,
                            "total_time_room_denial": total_time_room_denial,
                            "total_time_pet_inside_while_room_denial_was_active": total_time_pet_inside_while_room_denial_was_active
                        }
                    }
                else:  # no measurements present? This is a new room!
                    statistics = statistics | {
                        room["_id"]: {
                            "name": room["profile"]["name"],
                            "tot_time_pet_inside": 0,
                            "num_of_times_it_entered_that_room": 0,
                            "last_time_timestamp": "Pet never accessed the room.",
                            "total_time_room_denial": 0,
                            "total_time_pet_inside_while_room_denial_was_active": 0
                        }
                    }

        return statistics

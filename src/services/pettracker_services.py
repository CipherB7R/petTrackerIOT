import itertools
from idlelib.run import Executive
from typing import Dict, Any
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
            filter( # get a device if its ID isn't the same of some faulted device and if one of its override room associations is contained inside the list_of_rooms_id_associated_with_faulted_devices
                lambda device: (device["_id"] not in [dev["_id"] for dev in list_of_faulted_devices])
                               and
                                    (
                                        (device["data"]["override_exit_side_room_id"] in list_of_rooms_id_associated_with_faulted_devices)
                                        or
                                        (device["data"]["override_entry_side_room_id"] in list_of_rooms_id_associated_with_faulted_devices)
                                    ),
                filter(
                    lambda dr: dr["type"] == "door",
                    digital_replicas
                )
            )
        )

        if len(list_of_devices_associated_to_faulted_rooms) == 0:
            return {} # no associations to be calculated, seems like the faulted devices were all associated to rooms with a single entry point or to the default room on both sides!

        # else, let's calculate the room changes...
        # simply put the default room id wherever a room in the list_of_rooms_id_associated_with_faulted_devices is.

        dictionary_doorIds_changes = {device_id:changes for (device_id, changes) in zip ( # a dictionary made of door IDs and suggested changes...

            [device["_id"] for device in list_of_devices_associated_to_faulted_rooms], # this is the list of keys for the dictionary to be returned by the service.
            # ...while the one below is the list of values of the dictionary to be returned as a result of our service.
            [ # list of changes dictionaries, one per device... MADE WITH A LIST COMPREHENSION...
                { # ...another dict comprehension... makes a dictionary of suggested changes based on the list of keys that associate the current device to a faulted room...
                    faulted_room_association_key: default_room_id for faulted_room_association_key in # the keys get associated to the default_room id
                    list( # make a list out of the filter iterator...
                        filter( # take the keys to the override room associations, if they associate the current device to a faulted room.
                            lambda k: device["data"][k] in list_of_rooms_id_associated_with_faulted_devices,
                            ['override_exit_side_room_id', 'override_entry_side_room_id']
                        )
                    )
                }
                |  # union operator for dicts, we'll unite the previous dict with another dict containing just the power_saving key suggested change...
                {  # the power status suggested doesn't account for the global power saving status... THAT'S A THING OF THE APPLICATION LEVEL. WE SHOULDN'T EVEN BE MENTIONING IT HERE, BUT SINCE WE ARE LEARNING, BETTER TO SPECIFY IT
                    "power_saving_mode_status": device["data"]["override_exit_side_room_id"] == device["data"]["override_entry_side_room_id"]
                }
                for device in list_of_devices_associated_to_faulted_rooms # LIST COMPREHENSION ENDLINE

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
            Execute the service on provided data.
            Args:
                data: Input data in any format. Must contain at least the "digital_replicas" key,
                      which in turn must contain all the data pertaining to the caller DT's room DR.
                      It requires the "room" digital_replicas to have the "measurements" data field.

                dr_type: The default is room since we are going to analyze only room DRs among all DRs associated to the DT

                attribute: Specific attribute to analyze
            Returns:
                A dictionary whose keys are the DR Ids of rooms, and whose values are the computed statistics.
            Throws:
                An exception if there is more than one DR whose vacancy status is false.
            """
        pass

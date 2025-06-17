from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from src.virtualization.digital_replica.dr_factory import DRFactory
from bson import ObjectId

# HTTP API v1 for pettracking application
# you can test it with the postman file!

pettracker_api = Blueprint('pettracker_api', __name__, url_prefix='/api/pettracker')


########################################################################################################################
#######   UTILITIES   ##################################################################################################
########################################################################################################################

# def get_current_pet_room_id():
#     # the current pet position is the room with vacancy status equal to false
#     # Find the bottle with this RFID tag
#     rooms = current_app.config["DR_FACTORY"].query_drs("room", {'data.vacancy_status': False}) # query may return more than 1 room with vacancy status equals to false
#     room = rooms[0]  # take the first - TODO add a room check for univocity of occupied room
#     return room["_id"]


def register_pettracker_blueprint(app):
    app.register_blueprint(pettracker_api)

# todo: add door, room and smart_home DRs directly to their DT counterparts, so use the APIs to create contemporarily DRs and associated DTs,
#       BUT ONLY WHEN YOU HAVE THE CODE SET TO MANAGE DRs associations (device-smart home, room-smart home, device->rooms) TOO!
#       for the demo, just create DTs at the moment, to fire up any needed services.
#       for the demo, you just need the statistical services of rooms and the services of smart homes. No need for door DT yet.

########################################################################################################################
#######   DOOR DR API   ################################################################################################
########################################################################################################################

@pettracker_api.route("/doors", methods=['POST'])
def create_door():
    """ API endpoint to create a door DR """
    try:
        data = request.get_json()
        dr_factory = current_app.config['DR_FACTORY']
        door = dr_factory.create_dr('door',
                                    data)  # this will create a dr, validate it through the schema registry and save it on MongoDB
        return jsonify({"status": "success", "message": "Door created successfully", "door_id": door["_id"]}), 201
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/doors/<door_id>", methods=['PUT'])
def update_door(door_id): # this is idempotent... we can use PUT
    """Update door details"""

    # WHEN YOU UPDATE, update_dr REPLACES THE DR FIELDS WITH THOSE OF THE REQUEST DATA!
    # IF YOU WANT TO SAVE LISTS FROM AN OVERWRITE, YOU NEED TO APPEND THE update_dr'S list's field elements
    # TO THE LISTS RETRIEVED FROM THE DATABASE
    # BTW, when you use $set in mongodb queries, it may DELETE sub keys if you don't specify em all for a field!!!! WATCHOUT!
    # this doesn't happen to us, because update_dr takes care of this caveat by getting the dr current data and appending
    # new data through the pydantic model (see exclude_unset flag when we call model_dump())
    try:
        data = request.get_json()
        update_data = {}

        #Handle profile updates
        if "profile" in data:
            update_data["profile"] = data["profile"]
        #Handle data updates
        if "data" in data:
            update_data["data"] = data["data"]

            # The list of measurements gets appended, not replaced...
            # if and only if there was no measurement before.
            current_dr = current_app.config["DR_FACTORY"].get_dr("door", door_id)
            if not current_dr:
                return jsonify({"error": "Door not found"}), 404


            if "measurements" in data["data"]:
                if "measurements" in current_dr["data"]:
                    if len(current_dr["data"]["measurements"]) != 0:
                        update_data["data"]["measurements"] = [] # we clear the list in case we already have measurements

            # entry and exit side room association updates get automatically applied to other side, even during a fault.
            # if an update has to be applied, and it contains all the 4 keys (2 normal and 2 override), then precedence
            # is given to the value of the "normal" association.
            # for each room association field present in the update...
            # check if the key is an "override" one. if it is, check if the "normal" version is defined in the update...
            # if it is, then copy the "normal value" on both versions. If it is NOT, copy the override one.
            if "entry_side_room_id" in data["data"]:
                update_data["data"]["override_entry_side_room_id"] = update_data["data"]["entry_side_room_id"]
            else:
                if "override_entry_side_room_id" in data["data"]:
                    update_data["data"]["entry_side_room_id"] = update_data["data"]["override_entry_side_room_id"]

            if "exit_side_room_id" in data["data"]:
                update_data["data"]["override_exit_side_room_id"] = update_data["data"]["exit_side_room_id"]
            else:
                if "override_exit_side_room_id" in data["data"]:
                    update_data["data"]["exit_side_room_id"] = update_data["data"]["override_exit_side_room_id"]

            # todo: shall we implement mqtt state update here, as per FR8? That includes
            #  denial setting... check denial state of new room assignment and act accordingly...
            #  and
            #  power saving state changes... check if entry side id is now the same as other side. If it is, wake up device (implement MQTT update here?).

        #Always update the 'updated at' timestamp
        update_data["metadata"] = {"updated_at": datetime.utcnow()}

        current_app.config["DR_FACTORY"].update_dr("door", door_id, update_data)
        return jsonify({"status": "success", "message": "Door updated successfully"}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/doors/<door_id>", methods=['GET'])
def get_door(door_id):
    """Get door details"""
    try:
        door = current_app.config["DR_FACTORY"].get_dr("door", door_id)
        if not door:
            return jsonify({"error": "Door not found"}), 404
        return jsonify(door), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/doors/<door_id>", methods=['DELETE'])
def delete_door(door_id):
    """Delete a door only if there is no reference to it in some smart home"""
    try:
        door = current_app.config["DR_FACTORY"].get_dr("door", door_id)
        if not door:
            return jsonify({"error": "Door not found"}), 404

        # we can't delete a door if there exists some reference in a smart home (the devices can't go "poof"!)
        filters = {"list_of_devices": door["_id"]   # https://www.mongodb.com/docs/manual/tutorial/query-arrays/#query-an-array-for-an-element
            #                         {"$all": [door["_id"]]} # https://www.mongodb.com/docs/manual/tutorial/query-arrays/#match-an-array
        }

        smart_homes_associated_to_door = current_app.config["DR_FACTORY"].query_drs("smart_home", filters)
        if smart_homes_associated_to_door:
            return jsonify({"error": "Door cannot be deleted, it is still associated to some smart homes!"}), 400

        current_app.config["DR_FACTORY"].delete_dr("door", door_id)
        return jsonify({"status": "success", "message": "Door deleted successfully"}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/doors", methods=['GET'])
def list_doors():
    """Get all doors with optional filtering about power status and power saving mode status"""
    try:
        filters = {}

        if request.args.get('power_saving_mode_status'):
            filters["data.power_saving_mode_status"] = request.args.get('power_saving_mode_status')
        if request.args.get('power_status'):
            filters["data.power_status"] = request.args.get('power_status')

        doors = current_app.config["DR_FACTORY"].query_drs("door", filters)
        return jsonify({"doors": doors}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


# Deactivated, we do this only via MQTT updates.
# @pettracker_api.route("/doors/<door_id>/measurements", methods=['POST'])
# def add_door_measurements(door_id):
#     """Add a new measurement to a door, which means firing the FR1 sequential flowchart"""
#     try:
#
#         data = request.get_json()
#         if not data.get('measure_type') or 'value' not in data or 'timestamp' not in data:
#             return jsonify({"error": "Missing required measurement fields"}), 400
#
#         dr_factory = current_app.config["DR_FACTORY"]
#         #  get current door data
#         door = dr_factory.get_dr("door", door_id)
#
#         if not door:
#             return jsonify({"error": "Door not found"}), 404
#
#         # update the DR, add the measurement.
#
#
#         # now, get the smart_home dt associated to the door dr
#         # (déjà vu? For the telegram api we get the smart home dt thanks to the telegram user id instead)
#
#         # todo: the pet position update service can call the pet localization service!
#         # todo: must implement a mutex (per user) to avoid concurrency in updates to the position... we can do it in a service
#         # Fire up the pet "vacancy status update" service to manage the change
#         #1. take the smart_home dr associated to the smart_home dt, and load the data in the obligatory digital_replicas key
#         #2. take the door dr associated to the new measurement and put it in the "update_dr"
#         #3. take the new measurement and put it the other "measurement_update" key
#
#
#
#         #We need to register the measurement
#         measurement = {
#             "measure_type": data['measure_type'],
#             "value": data['value'],
#             "timestamp": datetime.utcnow()
#         }
#
#         update_data = {
#             "data": {
#                 "measurements": room['data']['measurements'] + [measurement],
#                 "bottles": room['data']['bottles']  # Include sempre la lista bottles aggiornata
#             },
#             "metadata": {
#                 "updated_at": datetime.utcnow()
#             }
#         }
#         current_app.config['DB_SERVICE'].update_dr("room", room_id, update_data)
#         return jsonify({
#             "status": "success",
#             "message": "Measurement processed successfully"
#         }), 200
#     except Exception as e:
#        current_app.logger.error(e)
#         return jsonify({"error": str(e)}), 500


########################################################################################################################
#######   ROOM DR API   ################################################################################################
########################################################################################################################


@pettracker_api.route("/rooms", methods=['POST'])
def create_room():
    try:
        data = request.get_json()
        dr_factory = current_app.config['DR_FACTORY']
        room = dr_factory.create_dr('room',
                                    data)  # this will create a dr, validate it through the schema registry and save it on MongoDB
        return jsonify({"status": "success", "message": "Room created successfully", "room_id": room["_id"]}), 201
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/rooms/<room_id>", methods=['PUT'])
def update_room(room_id): # this one is idempotent too, we can use PUT
    """Update room details"""
    # WHEN YOU UPDATE, update_dr REPLACES THE DR FIELDS WITH THOSE OF THE REQUEST DATA!
    # IF YOU WANT TO SAVE LISTS FROM AN OVERWRITE, YOU NEED TO APPEND THE update_dr'S list's field elements
    # TO THE LISTS RETRIEVED FROM THE DATABASE
    # BTW, when you use $set in mongodb queries, it may DELETE sub keys if you don't specify em all for a field!!!! WATCHOUT!
    # this doesn't happen to us, because update_dr takes care of this caveat by getting the dr current data and appending
    # new data through the pydantic model (see exclude_unset flag when we call model_dump())

    try:
        data = request.get_json()
        update_data = {}

        # if the room is one of the Somewhere else room, FAIL WITH ERROR! YOU CAN'T MODIFY IT!
        current_dr = current_app.config["DR_FACTORY"].get_dr("room", room_id)
        if not current_dr:
            return jsonify({"error": "Room not found"}), 404

        if current_dr["profile"]["name"] == 'Somewhere else':
            raise Exception("YOU CAN'T MODIFY A DEFAULT ROOM!")

        #Handle profile updates
        if "profile" in data:
            update_data["profile"] = data["profile"]
        #Handle data updates
        if "data" in data:
            update_data["data"] = data["data"]

            # The list of measurements gets appended, not replaced...
            # if and only if there was no measurement before.

            if "measurements" in data["data"]:
                if "measurements" in current_dr["data"]:
                    if len(current_dr["data"]["measurements"]) != 0:
                        update_data["data"]["measurements"] = [] # we clear the list in case we already have measurements




        #Always update the 'updated at' timestamp
        update_data["metadata"] = {"updated_at": datetime.utcnow()}

        current_app.config["DR_FACTORY"].update_dr("room", room_id, update_data)
        return jsonify({"status": "success", "message": "Room updated successfully"}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/rooms/<room_id>", methods=['GET'])
def get_room(room_id):
    """Get room details"""
    try:
        room = current_app.config["DR_FACTORY"].get_dr("room", room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        return jsonify(room), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/rooms/<room_id>", methods=['DELETE'])
def delete_room(room_id):
    """Delete a room"""
    try:
        room = current_app.config["DR_FACTORY"].get_dr("room", room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404

        # we can't delete a "somewhere else" default room.
        if room["profile"]["name"] == "Somewhere else":
            return jsonify({"error": "You can't delete the 'somewhere else' default room!"}), 404

        # we can't delete a room if there exists some door whose sides are associated to it!
        filters = {"$or": # https://www.mongodb.com/docs/manual/reference/operator/query/or/#syntax
            [
                {"data.entry_side_room_id": room_id}, {"data.exit_side_room_id": room_id},
                {"data.override_entry_side_room_id": room_id}, {"data.override_exit_side_room_id": room_id}
            ]
        }

        doors_associated_to_room = current_app.config["DR_FACTORY"].query_drs("door", filters)
        if doors_associated_to_room:
            return jsonify({"error": "Room cannot be deleted, some door devices are still associated to it!"}), 400

        # we can't delete a room if there exists some reference in a smart home (the rooms can't go "poof"!)
        filters = {"list_of_rooms": room["_id"]
                   # https://www.mongodb.com/docs/manual/tutorial/query-arrays/#query-an-array-for-an-element
                   #                {"$all": [room["_id"]]} # https://www.mongodb.com/docs/manual/tutorial/query-arrays/#match-an-array
                   }

        smart_homes_associated_to_room = current_app.config["DR_FACTORY"].query_drs("smart_home", filters)
        if smart_homes_associated_to_room:
            return jsonify({"error": "Room cannot be deleted, it is still associated to some smart homes!"}), 400

        current_app.config["DR_FACTORY"].delete_dr("room", room_id)
        return jsonify({"status": "success", "message": "Room deleted successfully"}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/rooms", methods=['GET'])
def list_rooms():
    "Get all rooms with optional filtering about vacancy status and denial status"
    try:
        filters = {}

        if request.args.get('vacancy_status'):
            filters["data.vacancy_status"] = request.args.get('vacancy_status')
        if request.args.get('denial_status'):
            filters["data.denial_status"] = request.args.get('denial_status')

        rooms = current_app.config["DR_FACTORY"].query_drs("room", filters)
        return jsonify({"rooms": rooms}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


########################################################################################################################
#######   SMART HOME DR API   ##########################################################################################
########################################################################################################################


@pettracker_api.route("/smart_homes", methods=['POST'])
def create_smart_home():
    room = None
    try:
        data = request.get_json()
        dr_factory = current_app.config['DR_FACTORY']
        # all smart homes come with only one room, the somewhere else room, by default.
        # The API users can't specify rooms when they create a smart home
        room = dr_factory.create_dr('room',
                                    {'profile': {
                                        'name': 'Somewhere else'
                                    },
                                        'data': {
                                            'vacancy_status': False,
                                            # pet will be here, in the only room of the smart home...
                                            'denial_status': False,  # denial status is locked to False!
                                            'last_time_accessed': datetime.utcnow(),
                                            # ...  starting from creation of smart home!
                                            'measurements': []
                                        }
                                    }
                                    )
        if 'data' not in data:
            data['data'] = {}

        data['data']['default_room_id'] = room["_id"]
        data['data']['list_of_rooms'] = [room["_id"]] # replace every content of this initial data with this list containing only the defaul room.

        smart_home = dr_factory.create_dr('smart_home',
                                          data)  # this will create a dr, validate it through the schema registry and save it on MongoDB
        return jsonify({"status": "success", "message": "smart_home created successfully",
                        "smart_home_id": smart_home["_id"]}), 201
    except Exception as e:
        current_app.logger.error(e)
        if room:
            # smart home creation failed, delete the default room...
            current_app.config["DR_FACTORY"].delete_dr("room", room['_id'])
        return jsonify({"error": str(e)}), 500

def _initialize_room_associations_of_device(door_id, somewhere_else_room_id):
    current_app.config["DR_FACTORY"].update_dr("door", door_id,
                                               {"data":
                                                   {
                                                       "power_saving_mode_status": True,
                                                       "entry_side_room_id": somewhere_else_room_id,
                                                       "exit_side_room_id": somewhere_else_room_id,
                                                       "override_entry_side_room_id": somewhere_else_room_id,
                                                       "override_exit_side_room_id": somewhere_else_room_id,
                                                   }})

    # todo: shall we add mqtt update to put the device in sleep mode (since same room associations on both sides)
    #  and deactivate all denial settings?
    #  if power saving was not active, send mqtt message; deactivate denial setting anyway... bla bla bla


@pettracker_api.route("/smart_homes/<smart_home_id>", methods=['PATCH'])
def update_smart_home(smart_home_id): # THIS ONE IS NOT IDEMPOTENT, WE CAN'T USE PUT. WE USE PATCH INSTEAD
    """Update smart_home details in a safe way for the tracking application"""
    # WHEN YOU UPDATE, update_dr REPLACES THE DR FIELDS WITH THOSE OF THE REQUEST DATA!
    # IF YOU WANT TO SAVE LISTS FROM AN OVERWRITE, YOU NEED TO APPEND THE update_dr'S list's field elements
    # TO THE LISTS RETRIEVED FROM THE DATABASE
    # BTW, when you use $set in mongodb queries, it may DELETE sub keys if you don't specify em all for a field!!!! WATCHOUT!
    # this doesn't happen to us, because update_dr takes care of this caveat by getting the dr current data and appending
    # new data through the pydantic model (see exclude_unset flag when we call model_dump())

    try:
        data = request.get_json()
        update_data = {}

        #Handle profile updates
        if "profile" in data:
            update_data["profile"] = data["profile"]

        #Handle data updates
        if "data" in data:
            update_data["data"] = data["data"]

            print(update_data["data"]["list_of_devices"])

            # any overwrite to the default_room_id gets blocked.
            update_data["data"].pop("default_room_id", None)

            # The list of rooms and devices gets appended, not replaced.
            current_dr = current_app.config["DR_FACTORY"].get_dr("smart_home", smart_home_id)
            if not current_dr:
                return jsonify({"error": "Smart home not found"}), 404

            if "list_of_rooms" in data["data"]:
                if "list_of_rooms" in current_dr["data"]:
                    update_data["data"]["list_of_rooms"].extend(current_dr["data"]["list_of_rooms"])


            if "list_of_devices" in data["data"]:
                # When a device gets (re)associated to a smart home,
                # its room associations get reinitialized with the "somewhere else's" room id!
                for door_id in data["data"]["list_of_devices"]:
                    # so, update the door DR associated to the device...
                    somewhere_else_room_id = current_dr["data"]["default_room_id"]
                    _initialize_room_associations_of_device(door_id, somewhere_else_room_id)

                if "list_of_devices" in current_dr["data"]:
                    update_data["data"]["list_of_devices"].extend(current_dr["data"]["list_of_devices"])

        #print(update_data)
        #Always update the 'updated at' timestamp
        update_data["metadata"] = {"updated_at": datetime.utcnow()}

        current_app.config["DR_FACTORY"].update_dr("smart_home", smart_home_id, update_data)
        return jsonify({"status": "success", "message": "smart_home updated successfully"}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/smart_homes/<smart_home_id>", methods=['PUT'])
def update_smart_home_unsafe(smart_home_id): # THIS ONE IS IDEMPOTENT, BUT ALLOWS BAD BEHAVIOR LIKE OVERWRITING ROOM ASSOCIATIONS! DATA MAY BE LOST, SO BLOCK THIS API IF NOT NEEDED.
    """Update smart_home details in an unsafe way for the tracking application, needed to reset lists fields that otherwise can only be appended with the safe update."""
    # WHEN YOU UPDATE, update_dr REPLACES THE DR FIELDS WITH THOSE OF THE REQUEST DATA!
    # IF YOU WANT TO SAVE LISTS FROM AN OVERWRITE, YOU NEED TO APPEND THE update_dr'S list's field elements
    # TO THE LISTS RETRIEVED FROM THE DATABASE
    # BTW, when you use $set in mongodb queries, it may DELETE sub keys if you don't specify em all for a field!!!! WATCHOUT!
    # this doesn't happen to us, because update_dr takes care of this caveat by getting the dr current data and appending
    # new data through the pydantic model (see exclude_unset flag when we call model_dump())
    try:
        data = request.get_json()
        update_data = {}

        #Handle profile updates
        if "profile" in data:
            update_data["profile"] = data["profile"]

        #Handle data updates
        if "data" in data:
            update_data["data"] = data["data"]

            # any overwrite to the default_room_id gets blocked.
            update_data["data"].pop("default_room_id", None)

            # The lists of rooms and devices GET REPLACED.
            current_dr = current_app.config["DR_FACTORY"].get_dr("smart_home", smart_home_id)
            if not current_dr:
                return jsonify({"error": "Smart home not found"}), 404

            if "list_of_devices" in data["data"]:
                # When a device gets (re)associated to a smart home,
                # its room associations get reinitialized with the "somewhere else's" room id!
                for door_id in data["data"]["list_of_devices"]:
                    # so, update the door DR associated to the device...
                    somewhere_else_room_id = current_dr["data"]["default_room_id"]
                    _initialize_room_associations_of_device(door_id, somewhere_else_room_id)


        #Always update the 'updated at' timestamp
        update_data["metadata"] = {"updated_at": datetime.utcnow()}

        current_app.config["DR_FACTORY"].update_dr("smart_home", smart_home_id, update_data)
        return jsonify({"status": "success", "message": "smart_home updated successfully"}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/smart_homes/<smart_home_id>", methods=['GET'])
def get_smart_home(smart_home_id):
    """Get smart_home details"""
    try:
        smart_home = current_app.config["DR_FACTORY"].get_dr("smart_home", smart_home_id)
        if not smart_home:
            return jsonify({"error": "smart_home not found"}), 404
        return jsonify(smart_home), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/smart_homes/<smart_home_id>", methods=['DELETE'])
def delete_smart_home(smart_home_id):
    """Delete a smart_home"""
    try:
        smart_home = current_app.config["DR_FACTORY"].get_dr("smart_home", smart_home_id)
        if not smart_home:
            return jsonify({"error": "smart_home not found"}), 404

        # we can't delete a "smart home" with more than 1 room or any number of devices associated to it.
        # why 1 room? Well, the default "somewhere else" default room is always present.
        if len(smart_home["data"]["list_of_rooms"]) > 1:
            return jsonify({"error": "You can't delete the smart home if there is more than 1 room!"}), 404
        elif len(smart_home["data"]["list_of_devices"]) > 0:
            return jsonify({"error": "You can't delete the smart home if there are devices associated to it!"}), 404

        current_app.config["DR_FACTORY"].delete_dr("smart_home", smart_home_id)

        # delete default room too, with smart home
        current_app.config["DR_FACTORY"].delete_dr("room", smart_home["data"]["default_room_id"])

        return jsonify({"status": "success", "message": "smart_home deleted successfully"}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500


@pettracker_api.route("/smart_homes", methods=['GET'])
def list_smart_homes():
    "Get all smart_homes with optional filtering about fault status and address"
    try:
        filters = {}

        if request.args.get('fault_status'):
            filters["data.fault_status"] = request.args.get('fault_status')
        if request.args.get('address'):
            filters["profile.address"] = request.args.get('address')

        smart_homes = current_app.config["DR_FACTORY"].query_drs("smart_home", filters)
        return jsonify({"smart_homes": smart_homes}), 200
    except Exception as e:
        current_app.logger.error(e)
        return jsonify({"error": str(e)}), 500

# todo: deactivated till we implement the fault recovery service.
# @pettracker_api.route('/smart_homes/dt/services/fault_recovery/<dt_id>', methods=['POST'])
# def predict_optimal_room_assignments(dt_id):  # fault recovery service
#     """
#     Predicts optimal room assignments for a door sides within a smart home Digital Twin
#     Expected JSON body:
#     {
#         "smart_home_id": "string"  # ID of the smart home to analyze
#     }
#     """
#     try:
#         data = request.get_json()
#         if not data or 'smart_home_id' not in data:
#             return jsonify({'error': 'smart_home_id is required in request body'}), 400
#
#         # Get DT instance
#         dt = current_app.config['DT_FACTORY'].get_dt_instance(dt_id)
#         if not dt:
#             return jsonify({'error': 'Digital Twin not found'}), 404
#
#         # Execute temperature prediction service
#         try:
#             prediction = dt.execute_service(
#                 'FaultRecoveryService'
#             )
#             return jsonify(prediction), 200
#         except ValueError as ve:
#             return jsonify({'error': str(ve)}), 400
#         except Exception as e:
#        current_app.logger.error(e)
#             return jsonify({'error': f'Service execution failed: {str(e)}'}), 500
#
#     except Exception as e:
#        current_app.logger.error(e)
#         return jsonify({'error': str(e)}), 500

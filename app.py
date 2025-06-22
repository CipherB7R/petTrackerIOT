import telegram
from flask import Flask
from flask_cors import CORS

from src.application.pettracker_apis import register_pettracker_blueprint
from src.virtualization.digital_replica.dr_factory import DRFactory
from src.virtualization.digital_replica.schema_registry import SchemaRegistry
from database import Database
from src.digital_twin.dt_factory import DTFactory
from src.application.api import register_api_blueprints
from config.config_loader import ConfigLoader

from src.application.mqtt.mqtt_handler import DoorMQTTHandler

from pyngrok import ngrok
from telegram.ext import Application
import asyncio
import nest_asyncio
from src.application.telegram.config.settings import (
    TELEGRAM_TOKEN,
    NGROK_TOKEN,
    WEBHOOK_PATH,
    TELEGRAM_BLUE_PRINTS,
)
from src.application.telegram.handlers.base_handlers import setup_handlers
from src.application.telegram.routes.webhook_routes import register_webhook, init_routes

nest_asyncio.apply()
SERVER_PORT = 88


class FlaskServer:
    def __init__(self):
        self.app = Flask(__name__)
        CORS(self.app)

        # Initialize MQTT config

        self._init_components()
        self._register_blueprints()

        self.app.config["DEBUG"] = True
        self.ngrok_tunnel = None
        self.app.config["USE_RELOADER"] = False


    def _init_components(self):
        """Initialize all required components and store them in app config"""

        try:
            # Kill any existing ngrok process at startup
            import psutil

            for proc in psutil.process_iter(["pid", "name"]):
                if "ngrok" in proc.info["name"].lower():
                    try:
                        psutil.Process(proc.info["pid"]).terminate()
                        print(
                            f"Terminated existing ngrok process: PID {proc.info['pid']}"
                        )
                    except:
                        pass

            # Load our DR schema definitions (NET4UCA module)...
            schema_registry = SchemaRegistry()
            schema_registry.load_schema("door", "src/virtualization/templates/door.yaml")
            schema_registry.load_schema("room", "src/virtualization/templates/room.yaml")
            schema_registry.load_schema("smart_home", "src/virtualization/templates/smart_home.yaml")

            # Load database configuration
            db_config = ConfigLoader.load_database_config()
            connection_string = ConfigLoader.build_connection_string(db_config)

            # Create a persistent event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # NGROK ########################################
            # wait to kill processes
            import time
            time.sleep(2)

            # Setup ngrok
            # basically, we use a tunnel from OUR machine's port 88 to ngrok's public server port 80.
            # Ngrok provides us a port reachable for everyone on the internet, at the IP of the DNS
            # with URL self.ngrok_tunnel.public_url. The guys at NGrok set only the first part of the URL,
            # like 3009-79-26-81-187.ngrok-free.app, then we can set the remaining part, with /api/webhook/telegram
            # continues...
            ngrok.set_auth_token(NGROK_TOKEN)
            self.ngrok_tunnel = ngrok.connect(str(SERVER_PORT))
            # the ngrok public URL's path (the part after ...localhost:88/) and our machine' flask URL's path MUST MATCH!!!
            webhook_url = (
                f"{self.ngrok_tunnel.public_url}{TELEGRAM_BLUE_PRINTS}{WEBHOOK_PATH}"
            )
            print(f"Webhook URL: {webhook_url}")
            ####################################################



            # Now that we have a public reachable URL, which will relay to our port 88 all the HTTP requests,
            # we need to...
            # TELEGRAM INITIALIZATION########################
            application = Application.builder().token(TELEGRAM_TOKEN).read_timeout(30).write_timeout(30).build() # link our telegram bot
            application.loop = loop # link an asyncronous event handler which will loop constantly waiting for events
            setup_handlers(application) # the telegram library provides us a way to link different routines (handlers) based on the content of the event
                                        # (like a message to the bot, if the message contains a command or is a natural language message without commands...)
                                        # The library does it by implementing by itself a series of filters and a regular expression machine: that machine acts
                                        # on top of the event's content (be it text or binary); we can provide regular expressions or basic filters WHEN WE
                                        # LINK THE HANDLERS WITH THE application.add_handler(filter, handler_routine) method!

            init_routes(application) # this just copies the telegram library's application object into the webhook_routes namespace...
                                     # later, when we call functions from the webhook_routes.py file, they will all act on its global variable "application"
                                     # which now contains the current file's application object.
            loop.run_until_complete(application.initialize()) # with these three we start telegram's library internal coroutines which will receive the BOT HTTPS requests and pass them to our handlers...
            loop.run_until_complete(application.start())
            loop.run_until_complete(application.bot.set_webhook(webhook_url))
            ################################################

            # Initialize DatabaseService with populated schema_registry
            db_service = Database(
                connection_string=connection_string,
                db_name=db_config["settings"]["name"],
                schema_registry=schema_registry,
            )
            db_service.connect()
            #db_service.wipe_test_db()

            self.app.config["MQTT_CONFIG"] = {
                "broker": "127.0.0.1",  # i installed Oracle's mosquitto broker on the local machine
                "port": 1883,
            }
            # Initialize MQTT handler
            self.mqtt_handler = DoorMQTTHandler(self.app)

            # Initialize DTFactory
            dt_factory = DTFactory(db_service, schema_registry)

            # Initialize DRFactory
            dr_factory = DRFactory(db_service, schema_registry)

            # Store references
            self.app.config["SCHEMA_REGISTRY"] = schema_registry
            self.app.config["DB_SERVICE"] = db_service
            self.app.config["DT_FACTORY"] = dt_factory
            self.app.config["DR_FACTORY"] = dr_factory
            self.app.config["TELEGRAM_BOT"] = application.bot
            self.app.config["TELEGRAM_APPLICATION"] = application
            self.app.config["MQTT_HANDLER"] = self.mqtt_handler

        except Exception as e:
            print(f"Initialization error: {str(e)}")
            if self.ngrok_tunnel:
                ngrok.disconnect(self.ngrok_tunnel.public_url)
            raise e

    def _register_blueprints(self):
        """Register all API blueprints"""
        register_api_blueprints(self.app)
        register_pettracker_blueprint(self.app)
        register_webhook(self.app)  # ----> TELEGRAM

    def run(self, host="0.0.0.0", port=SERVER_PORT):
        """Run the Flask server"""
        try:
            self.mqtt_handler.start()
            self.app.run(host=host, port=port, use_reloader=False, debug=True)
        finally:
            # Cleanup on server shutdown
            if "DB_SERVICE" in self.app.config:
                self.app.config["DB_SERVICE"].disconnect()
            if self.ngrok_tunnel:
                ngrok.disconnect(self.ngrok_tunnel.public_url)
            if self.mqtt_handler:
                self.mqtt_handler.stop()


if __name__ == "__main__":
    server = FlaskServer()
    server.run()

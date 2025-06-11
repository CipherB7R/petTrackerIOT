# mqtt_handler.py

Here is the code needed for the Flask's MQTT client: 
thanks to this file Flask can receive/send publish messages from/to Doors DRs (NodeMCUs).

When the MQTT handler receives a message from the Mosquitto Broker,
it scans its topic using the code contained in the _on_message subroutine.
Based on the topic, the message gets relayed to one of the sub-handlers defined by us
(one or more per functional requirement).

When the Flask server needs to communicate with a DR, it can do so thanks to the
methods defined at the end of the DoorMQTTHandler class' definition: for example,
if we want to set the denial setting for the entry side of a Door DR device, we can use
the publish_denial_setting() method, without needing to rewrite the code
everywhere we need to do so.

# Telegram subfolder
## config
This subfolder contains the settings.py python script: we use it to set the remote NGrok's and local Flask's webhook URL
and to load the secret tokens needed to communicate with Ngrok's and Telegram's services.
## routes and (telegram) handlers
The python-telegram-bot package lets us control the pettracker telegram bot thanks to a simple yet effective interface. 

The Telegram Bot will communicate with the NGrok's webhook PUBLIC URL "https://something-somenumbers-something.ngrok-free.app/api/webhook/telegram".

The Bot's HTTP requests landing on that NGrok's URL will just get tunneled to our localhost:88 port, at the "http://localhost:8/api/webhook/telegram" url. 

From there, Flask will pass those HTTP requests to the Telegram Blueprint (Think of a Blueprint as just Flask's way of calling a Flask server module) at the route /telegram with prefix /api/webhook. 

The telegram_webhook() routine associated with the route /api/webhook/telegram will handle all the telegram bot's requests:
it will pass them as "updates" (see the library docs to understand what an update is... for us, let's just say it is the Bot's HTTP message content)
to the python-telegram-bot library async event loop.

This package will just run that loop in a separate thread and wait for HTTP requests from the bot...

When the loop thread receives an update, it scans its content and, based on it, passes it to a SPECIFIC handler:
the ".../telegram/handlers" subfolder contains the base_handlers.py file that in turn contains lots of specialized handlers subroutines
to handle the telegram user's BOT commands & menu.



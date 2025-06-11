the app.py file was modified to include a connection to our local MQTT broker 
(we use Oracle's Mosquitto MQTT application installed as a Microsoft Windows' service on the same machine that runs Flask),
another tunneled connection to NGrok Webhook's services and some asynchronous loop event threads for both paho-MQTT and python-telegram-bot's libraries internals.
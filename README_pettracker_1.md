the app.py file was modified to include a connection to our local MQTT broker 
(we use Oracle's Mosquitto MQTT application installed as a Microsoft Windows' service on the same machine that runs Flask),
another tunneled connection to NGrok Webhook's services and some asynchronous loop event threads for both paho-MQTT and python-telegram-bot's libraries internals.



From the IOT architecture perspective, given the fact that this application isn’t a simple sensor node IOT one, in the sense that it doesn’t wait for the users to request an update about any device’s failure or prohibited room’s pet entry notification, we will have to violate the stratification of the NET4uCA framework. 

In fact, we decided that including some calls to application-level code (automatic failure recovery, telegram notifications etc...) in the virtualization layer code (MQTT handlers) was the only viable way to implement some functional requirements that needed automatic runs:

first, we update the relative DR data (since an MQTT handler has been called), then, instead of using polling to start the relevant automatic failure or entry checks to inform the user, we use the reception of that MQTT message to trigger application layer code, which will trigger in cascade digital twin layer code for state synchronization, service layer code for any computation to help with the upper levels, and virtualization layer code to update DR data. 
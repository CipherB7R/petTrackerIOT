from flask import current_app
import paho.mqtt.client as mqtt
from datetime import datetime
import json
import logging
import time
from threading import Thread, Event



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
        else:
            self.connected = False
            self.app.logger.error(f"Failed to connect to MQTT broker with code: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """Handle disconnection from broker"""
        self.connected = False
        if rc != 0:
            self.app.logger.warning(f"Unexpected disconnection from MQTT broker: {rc}")

    def _on_message(self, client, userdata, msg):
        """Handle incoming messages"""
        # TODO: insert here all handlers, one by one, filtering by topic.
        pass

    def publish_power_saving_mode(self, user: str, device_seq_number: int, state: bool, device_name: str = 'NodeMCU'):
        """Publish a power saving mode state change"""
        if not self.connected:
            self.app.logger.error("Not connected to MQTT broker")
            return

        topic = f"{self.base_topic}{user}/{device_name}@{device_seq_number}/PowerSaving"
        payload = {"state": state, "timestamp": datetime.utcnow().isoformat()}

        try:
            self.client.publish(topic, json.dumps(payload), qos=1, retain=True)
            self.app.logger.info(f"Published power saving state {state} for {device_name}@{device_seq_number} on behalf of user {user}")
        except Exception as e:
            self.app.logger.error(f"Error publishing LED state: {e}")

    def publish_denial_setting(self, user: str, device_seq_number: int, setting: bool, side: str, device_name: str = 'NodeMCU'):
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
            self.app.logger.info(f"Published denial setting {setting} for {device_name}@{device_seq_number} on behalf of user {user}")
            self.client.publish(topic, json.dumps(payload), qos=1, retain=True)
        except Exception as e:
            self.app.logger.error(f"Error publishing LED state: {e}")


    @property
    def is_connected(self):
        """Check if client is currently connected"""
        return self.connected

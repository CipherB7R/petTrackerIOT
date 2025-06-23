#define SERIAL_LOGGER 2
#define DEBUG_WITHOUT_SENSORS 1

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <ArduinoJson.hpp>

#define MILLIS_RESET_SENSOR_STATE 10000

#define buzzerPin D1
#define ledGreenPin D2
#define ledRedPin D5
#define irReceiverEntrySidePin D3
#define irReceiverExitSidePin D4
#define irReceiverHumanHeightPin D6
#define tripTransistor D7


#define ssid "Sorcerer"
#define password "TestingNodeMCU14706"

#define user "tabloid17"
#define name "NodeMCU@1" // name and sequential number separated by @
#define clientUniqueId 1001 //all nodeMCUs MQTT ID must start from 1001, and they are unique across all customers. We'll assign em at compile time!
                      // Hey, This is the first ever pettracker NodeMCU!


const char* mqtt_server = "172.20.10.3";
const uint16_t mqtt_port = 1883;
String base_topic = String("pettracker/");
String base_topic_plus_user = base_topic + user;
String base_topic_plus_device_name_plus_user = base_topic_plus_user + "/" + name;

String topic_passingByDetection = String("/passingByDetection");
String topic_denialEntrySetting = String("/denialEntrySetting");
String topic_denialExitSetting = String("/denialExitSetting");
String topic_powerStatus = String("/powerStatus");
String topic_powerSaving = String("/powerSaving");

bool o = false;
bool i = false;
bool h = false;

bool denialEntrySetting = false;
bool denialExitSetting = false;
bool powerStatus = true;
bool powerSaving = true;

WiFiClient espClient;
PubSubClient client(espClient);



typedef enum {ENTRY, EXIT} passingByAction;


String full_topic_passingByDetection = (base_topic_plus_device_name_plus_user + topic_passingByDetection);
String full_topic_denialEntrySetting = (base_topic_plus_device_name_plus_user + topic_denialEntrySetting);
String full_topic_denialExitSetting = (base_topic_plus_device_name_plus_user + topic_denialExitSetting);
String full_topic_powerStatus = (base_topic_plus_device_name_plus_user + topic_powerStatus);
String full_topic_powerSaving = (base_topic_plus_device_name_plus_user + topic_powerSaving);

void turn_on_visual_leds_according_to_state() {
  if(powerSaving) {
    digitalWrite(ledRedPin, LOW);
    digitalWrite(ledGreenPin, LOW);
    digitalWrite(tripTransistor, LOW);
  } else {

    digitalWrite(tripTransistor, HIGH);

    if (denialEntrySetting || denialExitSetting) {
      digitalWrite(ledRedPin, HIGH);
      digitalWrite(ledGreenPin, LOW);
    } else {
      digitalWrite(ledGreenPin, HIGH);
      digitalWrite(ledRedPin, LOW);
    }

  }
}

void publish_powerStatus(){

      JsonDocument doc; // will be destroyed when we exit the function

      doc["data"] = powerStatus;

      String jsonString;
      serializeJson(doc, jsonString);

      const char *msg = jsonString.c_str();
      #ifdef SERIAL_LOGGER
      Serial.print("Publishing passing by detection");
      Serial.println(String(msg));
      #endif
      #ifdef SERIAL_LOGGER
      Serial.print(full_topic_powerStatus);
      #endif
      client.publish(full_topic_powerStatus.c_str(), msg, true);


}

void publish_passingByDetection(passingByAction action){

      #ifdef SERIAL_LOGGER
      Serial.println("Got to publish a passing by detection!");
      #endif

      JsonDocument doc; // will be destroyed when we exit the function

      switch(action) {
        case ENTRY:
          doc["type"] = "entry";
          break;
        case EXIT:
          doc["type"] = "exit";
          break;
        default:
          return;
      }

      doc["value"] = 1.0;
      doc["timestamp"] = NOW();

      #ifdef SERIAL_LOGGER
      Serial.println("Setting the JSON document...");
      #endif

      String jsonString;
      serializeJson(doc, jsonString);

      #ifdef SERIAL_LOGGER
      Serial.println("Deserialized the JSON document...");
      #endif

      const char *msg = jsonString.c_str();

      #ifdef SERIAL_LOGGER
      Serial.print("Publishing passing by detection");
      Serial.println(String(msg));
      #endif
      #ifdef SERIAL_LOGGER
      Serial.print(full_topic_passingByDetection);
      #endif

      client.publish(full_topic_passingByDetection.c_str(), msg, false); // don't retain passing by detection messages, no need for those


}



void setup_wifi(){ //We can connect our board to the Internet
  delay(10);

  #ifdef SERIAL_LOGGER
  Serial.println();
  Serial.print("Connecting to ");
  Serial.print(ssid);
  #endif

  WiFi.begin(ssid,password);
  while(WiFi.status() != WL_CONNECTED){
    delay(500);

    #ifdef SERIAL_LOGGER
    Serial.print(".");
    #endif
  }

  #ifdef SERIAL_LOGGER
  Serial.println("");
  Serial.println("WiFi connected");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());
  #endif
}

void reconnectWiFi() {
  if (WiFi.status() != WL_CONNECTED) {

    #ifdef SERIAL_LOGGER
    Serial.println("WiFi connection lost. Reconnecting...");
    #endif

    WiFi.begin(ssid, password);

    while (WiFi.status() != WL_CONNECTED) {

      delay(1000);

      #ifdef SERIAL_LOGGER
      Serial.println("Reconnecting...");
      #endif
    }

    #ifdef SERIAL_LOGGER
    Serial.println("Reconnected to the WiFi network");
    #endif
  }
}

void reconnect(){

  //To reconnect to the topic
  while(!client.connected()){
    #ifdef SERIAL_LOGGER
    Serial.println("Attemting MQTT connection...");
    #endif

    // Construct the will message, to be used later
    JsonDocument doc;
    doc["data"] = false;

    String jsonString;
    serializeJson(doc, jsonString);

    // initialized in the setup. BTW, ALL MESSAGES SENT FROM THIS IMPLEMENTATION ARE SHORTER THAN 256 BYTES, SO NO WORRIES FOR THE PUBSUBCLIENT MQTT MAX PAYLOAD SIZE!
    const char* willMessage = jsonString.c_str();

    #ifdef SERIAL_LOGGER
    Serial.print("Initialized will message to: ");
    Serial.println(willMessage);
    Serial.print("Initialized will topic to: ");
    Serial.println(full_topic_powerStatus.c_str());
    #endif

    reconnectWiFi();

    String clientId = "ESP8266-";
    clientId += clientUniqueId; // String(random(0xffff),HEX); //all the devices must have different names


    if(client.connect(clientId.c_str(),
                      NULL,
                      NULL,
                      full_topic_powerStatus.c_str(),
                      0, // qos 0
                      true, // retain always the messages
                      willMessage,
                      false //clean session is false, so we can get messages sent by the server with retain flag == 1 when the client was offline!
                      )
                      ) {
      // client is connected and will was sent just in case it fails...
      #ifdef SERIAL_LOGGER
      Serial.println("Connected");
      #endif
      //subscribe to all the current device's topics with the + wildcard
      //String topic_to_subscribe_to = base_topic_plus_device_name_plus_user + "/+";
      // NO NEED TO INCLUDE ID INSIDE MESSAGES -> THESE TOPICS ARE READ ONLY FOR THE DEVICE. THE OTHER 2 ARE WRITE ONLY.
      client.subscribe(full_topic_denialEntrySetting.c_str(), 1); // subscribe with qos 1
      client.subscribe(full_topic_denialExitSetting.c_str(), 1); // subscribe with qos 1
      client.subscribe(full_topic_powerSaving.c_str(), 1); // subscribe with qos 1

      #ifdef SERIAL_LOGGER
      Serial.println("Subscribed to all devices topics, string used: ");
      Serial.println(full_topic_denialEntrySetting.c_str());
      Serial.println(full_topic_denialExitSetting.c_str());
      Serial.println(full_topic_powerSaving.c_str());
      Serial.println("-----------------------------------------------");
      #endif

      // Publish device configuration
      publish_powerStatus(); //flask server just needs to know when the device will turn on again


    } else {
      #ifdef SERIAL_LOGGER
      Serial.print("Failed, rc=");
      Serial.println(client.state());
      Serial.println(" try again in 5 seconds");
      #endif
      delay(5000);
    }
  }
}


void handler_topic_powerSaving(String msg) {
  JsonDocument doc;

  DeserializationError err = deserializeJson(doc, msg);

  if(err) {
    #ifdef SERIAL_LOGGER
    Serial.print("Couldn't deserialize message [");
    Serial.print(msg);
    Serial.println("]");
    switch (err.code()) {
      case DeserializationError::Ok:
          Serial.print(F("Deserialization succeeded"));
          break;
      case DeserializationError::InvalidInput:
          Serial.print(F("Invalid input!"));
          break;
      case DeserializationError::NoMemory:
          Serial.print(F("Not enough memory"));
          break;
      default:
          Serial.print(F("Deserialization failed"));
          break;
    }
    #endif
    return;
  }

  if(doc.containsKey("setting") && doc["setting"].is<bool>()) {
    powerSaving = doc["setting"];
    #ifdef SERIAL_LOGGER
    Serial.print("Power saving set to ");
    Serial.print(powerSaving);
    Serial.println("]");
    #endif
  }

  turn_on_visual_leds_according_to_state();

}

void handler_topic_denialEntrySetting(String msg) {
  JsonDocument doc;
   DeserializationError err = deserializeJson(doc, msg);

  if(err) {
    #ifdef SERIAL_LOGGER
    Serial.print("Couldn't deserialize message [");
    Serial.print(msg);
    Serial.println("]");
    switch (err.code()) {
      case DeserializationError::Ok:
          Serial.print(F("Deserialization succeeded"));
          break;
      case DeserializationError::InvalidInput:
          Serial.print(F("Invalid input!"));
          break;
      case DeserializationError::NoMemory:
          Serial.print(F("Not enough memory"));
          break;
      default:
          Serial.print(F("Deserialization failed"));
          break;
    }
    #endif
    return;
  }

  if(doc.containsKey("setting") && doc["setting"].is<bool>()) {
    denialEntrySetting = doc["setting"];
    #ifdef SERIAL_LOGGER
    Serial.print("Denial entry setting set to ");
    Serial.print(denialEntrySetting);
    Serial.println("]");
    #endif
  }


  turn_on_visual_leds_according_to_state();

}

void handler_topic_denialExitSetting(String msg){
  JsonDocument doc;

   DeserializationError err = deserializeJson(doc, msg);

  if(err) {
    #ifdef SERIAL_LOGGER
    Serial.print("Couldn't deserialize message [");
    Serial.print(msg);
    Serial.println("]");
    switch (err.code()) {
      case DeserializationError::Ok:
          Serial.print(F("Deserialization succeeded"));
          break;
      case DeserializationError::InvalidInput:
          Serial.print(F("Invalid input!"));
          break;
      case DeserializationError::NoMemory:
          Serial.print(F("Not enough memory"));
          break;
      default:
          Serial.print(F("Deserialization failed"));
          break;
    }
    #endif
    return;
  }


  if(doc.containsKey("setting") && doc["setting"].is<bool>()) {
    denialExitSetting = doc["setting"];
    #ifdef SERIAL_LOGGER
    Serial.print("Denial exit setting set to ");
    Serial.print(denialExitSetting);
    Serial.println("]");
    #endif
  }

  turn_on_visual_leds_according_to_state();

}


void callback(char* topic, byte* payload, unsigned int length) {
  #ifdef SERIAL_LOGGER
  Serial.print("Message arrived [");
  Serial.print(topic);
  Serial.println("]");
  #endif

  if(length > 0 && length <= MQTT_MAX_PACKET_SIZE) {
    String s_topic = String(topic);
    // Convert the payload to a string
    String s_message;
    for (int i = 0; i < length; i++) {
      s_message += (char)payload[i];
    }

    #ifdef SERIAL_LOGGER
    Serial.println(s_message);
    #endif

    // Switch on the topic and fire the appropriate handlers...
    if(s_topic.indexOf(topic_powerSaving) > 0) handler_topic_powerSaving(s_message);
    else if(s_topic.indexOf(topic_denialEntrySetting) > 0) handler_topic_denialEntrySetting(s_message);
    else if(s_topic.indexOf(topic_denialExitSetting) > 0) handler_topic_denialExitSetting(s_message);
    else {
      #ifdef SERIAL_LOGGER
      Serial.println("No handler defined for this topic.");
      #endif
    }
  }

}


void setup() {
  // put your setup code here, to run once:

  //set pin modes
  pinMode(tripTransistor, OUTPUT);
  pinMode(ledGreenPin, OUTPUT);
  pinMode(ledRedPin, OUTPUT);
  pinMode(buzzerPin, OUTPUT);
  pinMode(irReceiverEntrySidePin, INPUT); //todo: add the ir thingies
  pinMode(irReceiverExitSidePin, INPUT); //todo: add the ir thingies
  pinMode(irReceiverHumanHeightPin, INPUT); //todo: add the ir thingies

  #ifdef SERIAL_LOGGER
  Serial.begin(115200);
  #endif

  turn_on_visual_leds_according_to_state();

  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(callback);
}

bool is_outer_pet_sensor_triggered() {
  return digitalRead(irReceiverExitSidePin) == HIGH;
}

bool is_inner_pet_sensor_triggered() {
  return digitalRead(irReceiverEntrySidePin) == HIGH;
}

bool is_human_sensor_triggered() {
  return digitalRead(irReceiverHumanHeightPin) == HIGH;
}

typedef enum {} cat_position;

void update_sensor_states() {
  #if DEBUG_WITHOUT_SENSORS == 0
  // retrieves the pet sensor status for this round.
  o = is_outer_pet_sensor_triggered();
  i = is_inner_pet_sensor_triggered();
  h = is_human_sensor_triggered();
  #else
  static unsigned char state_test_list[43] = {
    0b000, 0b100, 0b110, 0b010, 0b000,
    0b000, 0b010, 0b110, 0b100, 0b000,
    0b000, 0b010, 0b011,
    0b000, 0b010, 0b000,
    0b000, 0b100, 0b000,
    0b000, 0b100, 0b110, 0b100, 0b000,
    0b000, 0b010, 0b110, 0b010, 0b000,
    0b000, 0b100, 0b110, 0b100, 0b110, 0b100, 0b000,
    0b000, 0b010, 0b110, 0b010, 0b110, 0b010, 0b000
    };
  static int index = 0;
  // rotate sensors states every 2 seconds, to simulate first an entry, then an exit...
  static unsigned long last_sensor_state_change_clocktime = 0;
  if((millis() - last_sensor_state_change_clocktime) > 2000) {
    last_sensor_state_change_clocktime = millis();
    // the sensors rotate like this for the entry... state is 3 bits (o,i,h), outer, inner, and human sensor,
    // oih    oih    oih    oih    oih
    // 000 -> 100 -> 110 -> 010 -> 000
    // then for the exit...
    // oih    oih    oih    oih    oih
    // 000 -> 010 -> 110 -> 100 -> 000
    // after these checks, we simulate a human passing like this...
    // 000 -> 010 -> 011 -> xxx (we go to the next)
    // after it, we simulate a pet hesitation...
    // 000 -> 010 -> 000
    // 000 -> 100 -> 000
    // 000 -> 100 -> 110 -> 100 -> 000
    // 000 -> 010 -> 110 -> 010 -> 000
    // 000 -> 100 -> 110 -> 100 -> 110 -> 100 -> 000
    // 000 -> 010 -> 110 -> 010 -> 110 -? 010 -> 000
    o = state_test_list[index]&0b100;
    i = state_test_list[index]&0b010;
    h = state_test_list[index]&0b001;
    #ifdef SERIAL_LOGGER
      Serial.print("Testing entry... index ");
      Serial.print(index);
      Serial.print(" :");
      Serial.print(o);
      Serial.print(i);
      Serial.println(h);
    #endif
    index = (index + 1) % 43;
  }
  #endif
}

bool is_entry_cycle_active = false; //See figure 1.1
bool is_exit_cycle_active = false; //See figure 1.2
bool pet_between_sensors = false;
bool pet_is_about_to_commit_action = false;

void reset_sensing_states() {
  is_entry_cycle_active = false; //See figure 1.1
  is_exit_cycle_active = false; //See figure 1.2
  pet_between_sensors = false;
  pet_is_about_to_commit_action = false;
}

void buzz(){
  digitalWrite(buzzerPin, HIGH);
  delay(1000);
  digitalWrite(buzzerPin, LOW);
}

void check_pet_action() {
  // we enter two different code flows depending on which pet-level sensor gets triggered first.
  static unsigned long last_state_change_clocktime = 0;

  bool is_any_state_active = is_entry_cycle_active || is_exit_cycle_active || pet_between_sensors || pet_is_about_to_commit_action;
  if(((millis() - last_state_change_clocktime) > MILLIS_RESET_SENSOR_STATE) && is_any_state_active) {
    reset_sensing_states(); // to unblock
  }

  // priority to the hesitations: It's really uncommon for a pet to go at the speed of light
  // and making the sensors go ON and OFF at the same time to signal a passing. It's more common for that to be a sensor glitch.
  // to go forward in step, the condition that makes us go back in step must not be active at the same time,
  // otherwise we go back in state transition to prevent impossible states.

  update_sensor_states();

  if(h) {
    // reset because human passed
    #ifdef SERIAL_LOGGER
      Serial.println("Human passed! resetting and sleeping...");
    #endif
      reset_sensing_states();
      delay(2000); // sleep for 2 seconds!
    #ifdef SERIAL_LOGGER
      Serial.println("Rebegin tracking...");
    #endif

    return;
  }

  if(!pet_is_about_to_commit_action) { //not in phase 3
    if(!pet_between_sensors) { //not in phase 2
      if(is_entry_cycle_active && !(is_exit_cycle_active)) { //entry cycle active...

        if(i && o) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet is now between sensors");
          #endif
          pet_between_sensors = true;
          last_state_change_clocktime = millis();
        }

        if(!o) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet hesitated.");
          #endif
          is_entry_cycle_active = false;
          last_state_change_clocktime = millis();
        }

      } else if (!(is_entry_cycle_active) && is_exit_cycle_active) { //exit cycle active instead...

        if(o && i) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet is now between sensors");
          #endif
          pet_between_sensors = true;
          last_state_change_clocktime = millis();
        }

        if(!i) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet hesitated.");
          #endif
          is_exit_cycle_active = false;
          last_state_change_clocktime = millis();
        }


      } else { // none of them active at the moment...
        // Outer pet sensor triggered? (priority to it, so we don't have to deal with both sensor triggered case... the pet will never be that fast, don't worry)
        if(o) {
            is_entry_cycle_active = true;
            #ifdef SERIAL_LOGGER
            Serial.println("Entry cycle activated");
            #endif
            last_state_change_clocktime = millis();
          return;
        }
        // Inner pet sensor triggered?
        if(i) {
            is_exit_cycle_active = true;
            #ifdef SERIAL_LOGGER
            Serial.println("Exit cycle activated");
            #endif
            last_state_change_clocktime = millis();
          return;
        }

      }
    } else { // in phase 2 (pet is between sensors)
      if(is_entry_cycle_active) { //distinguish where we started from... entry or exit flowchart?

        if(!o && i) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet is about to commit action...");
          #endif
          pet_is_about_to_commit_action = true;
          last_state_change_clocktime = millis();
        }

        if(!i) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet hesitated. Back at the starting line...");
          #endif
          pet_between_sensors = false;
          last_state_change_clocktime = millis();
        }

      } else if (is_exit_cycle_active) {

        if(!i && o) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet is about to commit action...");
          #endif
          pet_is_about_to_commit_action = true;
          last_state_change_clocktime = millis();
        }

        if(!o) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet hesitated. Back at the starting line...");
          #endif
          pet_between_sensors = false;
          last_state_change_clocktime = millis();
        }


      }
    }
  } else { // in phase 3 (pet is about to commit action)
    if(is_entry_cycle_active) { //diistinguish where we started from... entry or exit flowchart?

        if(!i && !o) {
          // PET ENTERED ROOM
          #ifdef SERIAL_LOGGER
            Serial.println("Pet entered room!");
          #endif
          publish_passingByDetection(ENTRY);
          //reset all flags...
          reset_sensing_states();
          //buzz if denial on the entry side is active
          if(denialEntrySetting) {
            buzz();
          }
        }

        if(o) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet hesitated. Back between sensors...");
          #endif
          pet_is_about_to_commit_action = false;
          last_state_change_clocktime = millis();
        }

      } else if (is_exit_cycle_active) {

        if(!o && !i) {
          // PET EXITED ROOM
          #ifdef SERIAL_LOGGER
            Serial.println("Pet exited room!");
          #endif
          publish_passingByDetection(EXIT);
          //reset all flags...
          reset_sensing_states();
          //buzz if denial on the exit side is active
          if(denialExitSetting) {
            buzz();
          }

        }

        if(i) {
          #ifdef SERIAL_LOGGER
            Serial.println("Pet hesitated. Back between sensors...");
          #endif
          pet_is_about_to_commit_action = false;
          last_state_change_clocktime = millis();

        }

      }
  }
}

void loop() {

  if(!client.connected()){
      #ifdef SERIAL_LOGGER
            Serial.println("Lost connection, reconnecting...");
          #endif
      reconnect();
  }

  //ok let's continuosly check for an entrance action... as per FR1-2 charts...
  if(!powerSaving)
    check_pet_action();


  client.loop(); // need to call this to check for new MQTT messages
  reconnectWiFi();
}



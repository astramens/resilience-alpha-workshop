#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <ArduinoJson.h>
#include <Ticker.h>
#include "secrets.h"

Ticker ledTimer;

enum LedMode { OFF, GREEN_FIXED, GREEN_BLINK, RED_FIXED, RED_BLINK };

volatile LedMode ledMode = OFF;
volatile uint32_t receivedAt = 0;
volatile uint32_t remainingMs = 0;
volatile uint32_t elapsedMs = 0;

void updateLed() {
    uint32_t age = millis() - receivedAt;
    LedMode mode = ledMode;

    if (age >= remainingMs || WiFi.status() != WL_CONNECTED) {
        mode = OFF;
    }

    bool blinkOn = ((elapsedMs + age) / 500) % 2 == 0;
    bool red = mode == RED_FIXED || (mode == RED_BLINK && blinkOn);
    bool green = mode == GREEN_FIXED || (mode == GREEN_BLINK && blinkOn);

    digitalWrite(D6, red ? HIGH : LOW);
    digitalWrite(D5, green ? HIGH : LOW);
}

void fetchCommand() {
    WiFiClient client;
    HTTPClient http;

    if (!http.begin(client, String(SERVER_URL) + "/api/device/led")) {
        ledMode = OFF;
        return;
    }

    http.setTimeout(1500);
    http.addHeader("Authorization", String("Bearer ") + LED_TOKEN);

    int status = http.GET();

    if (status != 200) {
        ledMode = OFF;
        Serial.printf("Erreur HTTP : %d\n", status);
        http.end();
        return;
    }

    StaticJsonDocument<512> document;
    DeserializationError error = deserializeJson(document, http.getString());
    http.end();

    if (error || !document["mode"].is<const char*>() ||
        !document["remaining_ms"].is<uint32_t>() ||
        !document["elapsed_ms"].is<uint32_t>()) {
        ledMode = OFF;
        Serial.println("Commande invalide");
        return;
    }

    String name = document["mode"].as<String>();
    LedMode nextMode = OFF;

    if (name == "green_fixed") nextMode = GREEN_FIXED;
    else if (name == "green_blink") nextMode = GREEN_BLINK;
    else if (name == "red_fixed") nextMode = RED_FIXED;
    else if (name == "red_blink_10") nextMode = RED_BLINK;

    ledMode = OFF;
    receivedAt = millis();
    remainingMs = min(document["remaining_ms"].as<uint32_t>(), uint32_t(120000));
    elapsedMs = document["elapsed_ms"].as<uint32_t>();
    ledMode = nextMode;

    static String previousMode;
    if (name != previousMode) {
        Serial.println("LED : " + name);
        previousMode = name;
    }
}

void setup() {
    digitalWrite(D5, LOW);
    digitalWrite(D6, LOW);
    pinMode(D5, OUTPUT);
    pinMode(D6, OUTPUT);

    Serial.begin(115200);
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    ledTimer.attach_ms(25, updateLed);
    Serial.println("Connexion au Wi-Fi...");
}

void loop() {
    static uint32_t lastPoll = 0;
    static bool connected = false;
    bool online = WiFi.status() == WL_CONNECTED;

    if (online && !connected) {
        Serial.print("Wi-Fi connecte. Adresse : ");
        Serial.println(WiFi.localIP());
    }
    connected = online;

    if (online && millis() - lastPoll >= 1000) {
        lastPoll = millis();
        fetchCommand();
    }

    delay(10);
}
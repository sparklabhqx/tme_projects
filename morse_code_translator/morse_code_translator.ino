#include <MD_MAX72xx.h>
#include <SPI.h>
#include <avr/pgmspace.h>

// MAX7219 8x32 4-in-1 matrix on Arduino UNO.
// DIN -> D11, CS/LOAD -> D10, CLK -> D13.
#define HARDWARE_TYPE MD_MAX72XX::FC16_HW
#define MAX_DEVICES 4

const uint8_t DATA_PIN = 11;
const uint8_t CS_PIN = 10;
const uint8_t CLK_PIN = 13;

const uint8_t BRIGHTNESS = 8;       // 0-15
const uint16_t DOT_MS = 200;
const uint16_t DASH_MS = DOT_MS * 3;
const uint16_t SYMBOL_GAP_MS = DOT_MS;
const uint16_t LETTER_GAP_MS = DOT_MS * 3;
const uint16_t WORD_GAP_MS = DOT_MS * 7;
const uint16_t SERIAL_IDLE_MS = 120;
const uint8_t MAX_MESSAGE_LENGTH = 80;

MD_MAX72XX matrix(HARDWARE_TYPE, DATA_PIN, CLK_PIN, CS_PIN, MAX_DEVICES);

const char MORSE_A[] PROGMEM = ".-";
const char MORSE_B[] PROGMEM = "-...";
const char MORSE_C[] PROGMEM = "-.-.";
const char MORSE_D[] PROGMEM = "-..";
const char MORSE_E[] PROGMEM = ".";
const char MORSE_F[] PROGMEM = "..-.";
const char MORSE_G[] PROGMEM = "--.";
const char MORSE_H[] PROGMEM = "....";
const char MORSE_I[] PROGMEM = "..";
const char MORSE_J[] PROGMEM = ".---";
const char MORSE_K[] PROGMEM = "-.-";
const char MORSE_L[] PROGMEM = ".-..";
const char MORSE_M[] PROGMEM = "--";
const char MORSE_N[] PROGMEM = "-.";
const char MORSE_O[] PROGMEM = "---";
const char MORSE_P[] PROGMEM = ".--.";
const char MORSE_Q[] PROGMEM = "--.-";
const char MORSE_R[] PROGMEM = ".-.";
const char MORSE_S[] PROGMEM = "...";
const char MORSE_T[] PROGMEM = "-";
const char MORSE_U[] PROGMEM = "..-";
const char MORSE_V[] PROGMEM = "...-";
const char MORSE_W[] PROGMEM = ".--";
const char MORSE_X[] PROGMEM = "-..-";
const char MORSE_Y[] PROGMEM = "-.--";
const char MORSE_Z[] PROGMEM = "--..";

const char MORSE_0[] PROGMEM = "-----";
const char MORSE_1[] PROGMEM = ".----";
const char MORSE_2[] PROGMEM = "..---";
const char MORSE_3[] PROGMEM = "...--";
const char MORSE_4[] PROGMEM = "....-";
const char MORSE_5[] PROGMEM = ".....";
const char MORSE_6[] PROGMEM = "-....";
const char MORSE_7[] PROGMEM = "--...";
const char MORSE_8[] PROGMEM = "---..";
const char MORSE_9[] PROGMEM = "----.";

const char *const MORSE_LETTERS[] PROGMEM = {
  MORSE_A, MORSE_B, MORSE_C, MORSE_D, MORSE_E, MORSE_F, MORSE_G,
  MORSE_H, MORSE_I, MORSE_J, MORSE_K, MORSE_L, MORSE_M, MORSE_N,
  MORSE_O, MORSE_P, MORSE_Q, MORSE_R, MORSE_S, MORSE_T, MORSE_U,
  MORSE_V, MORSE_W, MORSE_X, MORSE_Y, MORSE_Z
};

const char *const MORSE_DIGITS[] PROGMEM = {
  MORSE_0, MORSE_1, MORSE_2, MORSE_3, MORSE_4,
  MORSE_5, MORSE_6, MORSE_7, MORSE_8, MORSE_9
};

char message[MAX_MESSAGE_LENGTH + 1];
uint8_t messageLength = 0;
unsigned long lastSerialByteMs = 0;

void setup() {
  Serial.begin(9600);

  matrix.begin();
  matrix.control(MD_MAX72XX::INTENSITY, BRIGHTNESS);
  matrix.clear();

  Serial.println(F("Enter a sentence to convert to Morse code:"));
}

void loop() {
  readSerialMessage();

  if (messageLength > 0 && millis() - lastSerialByteMs >= SERIAL_IDLE_MS) {
    message[messageLength] = '\0';
    Serial.print(F("Sending: "));
    Serial.println(message);
    playMorseMessage(message);
    messageLength = 0;
    Serial.println(F("Enter a sentence to convert to Morse code:"));
  }
}

void readSerialMessage() {
  while (Serial.available() > 0) {
    char incoming = Serial.read();
    lastSerialByteMs = millis();

    if (incoming == '\r') {
      continue;
    }

    if (incoming == '\n') {
      if (messageLength > 0) {
        message[messageLength] = '\0';
        Serial.print(F("Sending: "));
        Serial.println(message);
        playMorseMessage(message);
        messageLength = 0;
        Serial.println(F("Enter a sentence to convert to Morse code:"));
      }
      continue;
    }

    if (messageLength < MAX_MESSAGE_LENGTH) {
      message[messageLength++] = incoming;
    }
  }
}

void playMorseMessage(const char *text) {
  bool previousWasSpace = true;

  for (uint8_t i = 0; text[i] != '\0'; i++) {
    char c = text[i];

    if (c >= 'a' && c <= 'z') {
      c -= 32;
    }

    if (c == ' ') {
      if (!previousWasSpace) {
        delay(WORD_GAP_MS - LETTER_GAP_MS);
      }
      previousWasSpace = true;
      continue;
    }

    char morse[6];
    if (!lookupMorse(c, morse, sizeof(morse))) {
      continue;
    }

    previousWasSpace = false;
    flashMorseSequence(morse);
    delay(LETTER_GAP_MS - SYMBOL_GAP_MS);
  }
}

bool lookupMorse(char c, char *buffer, size_t bufferSize) {
  const char *morsePtr = NULL;

  if (c >= 'A' && c <= 'Z') {
    morsePtr = (const char *)pgm_read_ptr(&MORSE_LETTERS[c - 'A']);
  } else if (c >= '0' && c <= '9') {
    morsePtr = (const char *)pgm_read_ptr(&MORSE_DIGITS[c - '0']);
  } else {
    return false;
  }

  strncpy_P(buffer, morsePtr, bufferSize);
  buffer[bufferSize - 1] = '\0';
  return true;
}

void flashMorseSequence(const char *sequence) {
  for (uint8_t i = 0; sequence[i] != '\0'; i++) {
    uint16_t duration = (sequence[i] == '.') ? DOT_MS : DASH_MS;
    flashMatrix(duration);
    delay(SYMBOL_GAP_MS);
  }
}

void flashMatrix(uint16_t durationMs) {
  setMatrix(true);
  delay(durationMs);
  setMatrix(false);
}

void setMatrix(bool on) {
  matrix.control(MD_MAX72XX::UPDATE, MD_MAX72XX::OFF);

  for (uint8_t column = 0; column < MAX_DEVICES * 8; column++) {
    matrix.setColumn(column, on ? 0xFF : 0x00);
  }

  matrix.control(MD_MAX72XX::UPDATE, MD_MAX72XX::ON);
  matrix.update();
}

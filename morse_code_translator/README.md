# Morse Code Translator

Arduino UNO project for flashing text as Morse code on a MAX7219 8x32 LED matrix.

## Hardware

- 1 x Arduino UNO
- 1 x MAX7219 8x32 dot matrix display, 4-in-1 module
- Jumper wires
- USB cable for programming the Arduino
- Breadboard or mounting hardware, optional

## Wiring

| MAX7219 matrix | Arduino UNO |
| --- | --- |
| VCC | 5V |
| GND | GND |
| DIN | D11 |
| CS or LOAD | D10 |
| CLK | D13 |

## Arduino Library

Install `MD_MAX72XX` by MajicDesigns from the Arduino Library Manager.
The sketch also uses Arduino's built-in `SPI` library.

## Upload

1. Open `morse_code_translator.ino` in the Arduino IDE.
2. Select `Arduino UNO` as the board.
3. Install the `MD_MAX72XX` library if it is not already installed.
4. Upload the sketch.
5. Open Serial Monitor at `9600` baud.
6. Type a sentence and press Send.

The sketch accepts serial messages with either a newline or `No Line Ending`.
Letters and digits are converted to Morse code. Unsupported punctuation is skipped.

## Timing

- Dot: 200 ms
- Dash: 600 ms
- Symbol gap: 200 ms
- Letter gap: 600 ms
- Word gap: 1400 ms

For each dot or dash, the whole matrix flashes on and then turns off.

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <TFT_eSPI.h>
#include "secrets.h"

// Passive joystick: COM -> GND, pressed == LOW
constexpr uint8_t JOY_UP = 32, JOY_DWN = 33, JOY_LFT = 26, JOY_RHT = 14;
constexpr uint8_t JOY_MID = 13, JOY_SET = 16, JOY_RST = 17;

// Portrait ST7789, 1-bit full-screen framebuffer
constexpr int16_t SCREEN_W = 240, SCREEN_H = 320;
constexpr uint16_t BG = 0, FG = 1;  // bitmap 0=white, 1=black
TFT_eSPI tft;
TFT_eSprite spr(&tft);
WebServer server(8765);

// Hub state
constexpr int16_t GROUND_Y = 276;
enum AppMode : uint8_t { MODE_DINO, MODE_SNAKE, MODE_CLOCK, MODE_WEATHER, MODE_DRAW, MODE_CHAT, MODE_TIMER };
enum RunState : uint8_t { READY, PLAYING, GAME_OVER };
AppMode activeMode = MODE_DINO;
RunState state = READY;
uint32_t lastFrameMs = 0;

struct Debounce { bool lastRaw = false, stable = false; uint32_t changedMs = 0; };
Debounce dbUp, dbDwn, dbLft, dbRht, dbMid, dbSet, dbRst;

// Dino state
constexpr int16_t DINO_X = 34, DINO_W = 24, DINO_H = 30;
constexpr float DINO_GRAVITY = 0.85f, DINO_JUMP_VY = -12.0f;
struct Obstacle { float x; int16_t w, h; bool scored; } obs[3];
float dinoY = GROUND_Y - DINO_H, dinoVy = 0, dinoSpeed = 4.0f;
bool dinoOnGround = true;
uint16_t dinoScore = 0;

// Snake state
constexpr int8_t SNAKE_COLS = 24, SNAKE_ROWS = 22;
constexpr int16_t SNAKE_CELL = 10, SNAKE_X0 = 0, SNAKE_Y0 = 52;
constexpr uint16_t SNAKE_MAX = SNAKE_COLS * SNAKE_ROWS;
struct Cell { uint8_t x, y; } snake[SNAKE_MAX], food;
enum Dir : uint8_t { DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT };
Dir snakeDir = DIR_RIGHT, snakeNextDir = DIR_RIGHT;
uint16_t snakeLen = 4, snakeScore = 0;
uint32_t snakeLastMoveMs = 0;

// Clock/weather/chat/timer state
String clockDate = "DATE", clockZone = "", weatherText = "", chatPrompt = "", chatAnswer = "";
uint32_t clockBaseMs = 0, clockBaseSecOfDay = 0;
uint32_t timerStartMs = 0, timerSeconds = 0;
String timerLabel = "timer";

// Drawing state
constexpr uint8_t DRAW_CELL = 4, DRAW_COLS = SCREEN_W / DRAW_CELL, DRAW_ROWS = 66;
constexpr int16_t DRAW_Y0 = 44;
bool drawGrid[DRAW_ROWS][DRAW_COLS];
uint8_t drawX = DRAW_COLS / 2, drawY = DRAW_ROWS / 2;
bool drawPen = true;
uint32_t drawLastMoveMs = 0;

// WiFi/server state
bool wifiWasConnected = false;
uint32_t lastWifiRetryMs = 0;

bool pressed(uint8_t pin) { return digitalRead(pin) == LOW; }

bool pressEdge(uint8_t pin, Debounce &d) {
  const bool raw = pressed(pin);
  const uint32_t now = millis();
  if (raw != d.lastRaw) { d.lastRaw = raw; d.changedMs = now; }
  if (now - d.changedMs >= 20 && raw != d.stable) {
    d.stable = raw;
    return d.stable;
  }
  return false;
}

String jsonString(const String &body, const char *key, const String &fallback = "") {
  String needle = String("\"") + key + "\"";
  int k = body.indexOf(needle); if (k < 0) return fallback;
  int colon = body.indexOf(':', k + needle.length()); if (colon < 0) return fallback;
  int q1 = body.indexOf('"', colon + 1); if (q1 < 0) return fallback;
  String out;
  for (int i = q1 + 1; i < body.length(); ++i) {
    char c = body[i];
    if (c == '"') break;
    if (c == '\\' && i + 1 < body.length()) {
      char e = body[++i];
      if (e == 'n') out += '\n'; else if (e == 't') out += ' '; else out += e;
    } else out += c;
  }
  return out;
}

long jsonLong(const String &body, const char *key, long fallback = 0) {
  String needle = String("\"") + key + "\"";
  int k = body.indexOf(needle); if (k < 0) return fallback;
  int p = body.indexOf(':', k + needle.length()); if (p < 0) return fallback;
  ++p; while (p < body.length() && isspace((unsigned char)body[p])) ++p;
  bool neg = false; if (p < body.length() && body[p] == '-') { neg = true; ++p; }
  long v = 0; bool any = false;
  while (p < body.length() && isdigit((unsigned char)body[p])) { any = true; v = v * 10 + (body[p++] - '0'); }
  return any ? (neg ? -v : v) : fallback;
}

String asciiClean(const String &s) {
  String out;
  bool lastSpace = false;
  for (int i = 0; i < s.length(); ++i) {
    uint8_t c = (uint8_t)s[i];
    if (c >= 32 && c <= 126) { out += (char)c; lastSpace = (c == ' '); }
    else if (!lastSpace) { out += ' '; lastSpace = true; }
  }
  out.trim();
  return out;
}

void drawWrapped(String text, int16_t x, int16_t y, int16_t w, uint8_t size, uint8_t maxLines) {
  text = asciiClean(text); text.replace('\n', ' ');
  const int chars = max(1, w / (6 * size));
  spr.setTextDatum(TL_DATUM); spr.setTextSize(size); spr.setTextColor(FG, BG);
  int lineNo = 0, pos = 0;
  while (pos < text.length() && lineNo < maxLines) {
    String line;
    while (pos < text.length() && text[pos] == ' ') ++pos;
    while (pos < text.length()) {
      int sp = text.indexOf(' ', pos); if (sp < 0) sp = text.length();
      String word = text.substring(pos, sp);
      if (line.length() && line.length() + 1 + word.length() > chars) break;
      if (!line.length() && word.length() > chars) { line = word.substring(0, chars); pos += chars; break; }
      if (line.length()) line += ' ';
      line += word; pos = sp + 1;
    }
    spr.drawString(line, x, y + lineNo * (8 * size + 4), 1);
    ++lineNo;
  }
}

void drawHeader(const char *title) {
  spr.setTextDatum(TC_DATUM); spr.setTextSize(2); spr.setTextColor(FG, BG);
  spr.drawString(title, SCREEN_W / 2, 8, 1);
  spr.drawFastHLine(10, 32, SCREEN_W - 20, FG);
}

void drawCentered(const char *a, const char *b = nullptr, const char *c = nullptr) {
  spr.setTextDatum(MC_DATUM); spr.setTextColor(FG, BG);
  spr.setTextSize(3); spr.drawString(a, SCREEN_W / 2, 92, 1);
  spr.setTextSize(2);
  if (b) spr.drawString(b, SCREEN_W / 2, 142, 1);
  if (c) spr.drawString(c, SCREEN_W / 2, 176, 1);
}

float rightMostObstacle() {
  float r = obs[0].x;
  for (uint8_t i = 1; i < 3; ++i) if (obs[i].x > r) r = obs[i].x;
  return r;
}

void randomizeObstacle(Obstacle &o, float x) {
  o.x = x; o.w = random(10, 21); o.h = random(24, 48); o.scored = false;
}

void resetDino() {
  dinoY = GROUND_Y - DINO_H; dinoVy = 0; dinoOnGround = true; dinoScore = 0; dinoSpeed = 4.0f;
  randomizeObstacle(obs[0], SCREEN_W + 40); randomizeObstacle(obs[1], SCREEN_W + 155); randomizeObstacle(obs[2], SCREEN_W + 285);
}

void updateDino(bool jump) {
  if (jump && dinoOnGround) { dinoVy = DINO_JUMP_VY; dinoOnGround = false; }
  dinoVy += DINO_GRAVITY; dinoY += dinoVy;
  if (dinoY >= GROUND_Y - DINO_H) { dinoY = GROUND_Y - DINO_H; dinoVy = 0; dinoOnGround = true; }
  float rightMost = rightMostObstacle();
  for (auto &o : obs) {
    o.x -= dinoSpeed;
    if (!o.scored && o.x + o.w < DINO_X) { o.scored = true; ++dinoScore; if (dinoSpeed < 7.0f) dinoSpeed += 0.08f; }
    if (o.x + o.w < 0) { randomizeObstacle(o, rightMost + random(95, 150)); rightMost = o.x; }
  }
}

bool dinoHit() {
  int16_t dx1 = DINO_X + 3, dx2 = DINO_X + DINO_W - 2, dy1 = (int16_t)dinoY + 2, dy2 = (int16_t)dinoY + DINO_H - 1;
  for (const auto &o : obs) {
    int16_t ox1 = (int16_t)o.x, ox2 = ox1 + o.w, oy1 = GROUND_Y - o.h;
    if (dx1 < ox2 && dx2 > ox1 && dy1 < GROUND_Y && dy2 > oy1) return true;
  }
  return false;
}

void drawDino(int16_t x, int16_t y) {
  spr.fillRect(x + 5, y + 6, 14, 18, FG); spr.fillRect(x + 13, y, 11, 10, FG);
  spr.fillRect(x + 21, y + 4, 3, 3, BG); spr.fillRect(x + 2, y + 12, 6, 5, FG);
  spr.fillRect(x + 6, y + 24, 5, 6, FG); spr.fillRect(x + 16, y + 24, 5, 6, FG);
}

void renderDino() {
  for (int16_t x = 0; x < SCREEN_W; x += 18) spr.drawFastHLine(x, GROUND_Y + 9, 7, FG);
  spr.drawFastHLine(0, GROUND_Y, SCREEN_W, FG); spr.fillRect(0, SCREEN_H - 12, SCREEN_W, 12, FG);
  for (const auto &o : obs) {
    int16_t x = (int16_t)o.x, y = GROUND_Y - o.h;
    spr.fillRect(x, y, o.w, o.h, FG);
    if (o.h > 32) { spr.fillRect(x - 5, y + 12, 7, 4, FG); spr.fillRect(x + o.w - 2, y + 20, 7, 4, FG); }
  }
  drawDino(DINO_X, (int16_t)dinoY);
  char buf[24]; snprintf(buf, sizeof(buf), "%u", dinoScore);
  spr.setTextDatum(TL_DATUM); spr.setTextSize(2); spr.setTextColor(FG, BG); spr.drawString(buf, 6, 6, 1);
  if (state == READY) drawCentered("DINO", "PRESS UP/MID", "OR POST CUE");
  if (state == GAME_OVER) { snprintf(buf, sizeof(buf), "SCORE %u", dinoScore); drawCentered("GAME OVER", buf, "PRESS UP/MID"); }
}

bool snakeOnCell(uint8_t x, uint8_t y) {
  for (uint16_t i = 0; i < snakeLen; ++i) if (snake[i].x == x && snake[i].y == y) return true;
  return false;
}

void placeFood() { do { food.x = random(SNAKE_COLS); food.y = random(SNAKE_ROWS); } while (snakeOnCell(food.x, food.y)); }

void resetSnake() {
  snakeLen = 4; snakeScore = 0; snakeDir = snakeNextDir = DIR_RIGHT;
  uint8_t cx = SNAKE_COLS / 2, cy = SNAKE_ROWS / 2;
  for (uint8_t i = 0; i < snakeLen; ++i) { snake[i].x = cx - i; snake[i].y = cy; }
  placeFood(); snakeLastMoveMs = millis();
}

void setSnakeDir(Dir d) {
  if ((snakeDir == DIR_UP && d == DIR_DOWN) || (snakeDir == DIR_DOWN && d == DIR_UP) ||
      (snakeDir == DIR_LEFT && d == DIR_RIGHT) || (snakeDir == DIR_RIGHT && d == DIR_LEFT)) return;
  snakeNextDir = d;
}

void updateSnake(bool action) {
  if (action && state == GAME_OVER) { resetSnake(); state = PLAYING; }
  if (pressed(JOY_UP)) setSnakeDir(DIR_UP); else if (pressed(JOY_DWN)) setSnakeDir(DIR_DOWN);
  else if (pressed(JOY_LFT)) setSnakeDir(DIR_LEFT); else if (pressed(JOY_RHT)) setSnakeDir(DIR_RIGHT);
  if (millis() - snakeLastMoveMs < 135 || state != PLAYING) return;
  snakeLastMoveMs = millis(); snakeDir = snakeNextDir;
  int16_t nx = snake[0].x, ny = snake[0].y;
  if (snakeDir == DIR_UP) --ny; else if (snakeDir == DIR_DOWN) ++ny; else if (snakeDir == DIR_LEFT) --nx; else ++nx;
  if (nx < 0 || nx >= SNAKE_COLS || ny < 0 || ny >= SNAKE_ROWS || snakeOnCell(nx, ny)) { state = GAME_OVER; return; }
  bool ate = (nx == food.x && ny == food.y);
  uint16_t newLen = snakeLen + (ate && snakeLen < SNAKE_MAX ? 1 : 0);
  for (int i = newLen - 1; i > 0; --i) snake[i] = snake[i - 1];
  snake[0] = {(uint8_t)nx, (uint8_t)ny}; snakeLen = newLen;
  if (ate) { ++snakeScore; placeFood(); }
}

void renderSnake() {
  spr.drawRect(SNAKE_X0, SNAKE_Y0, SNAKE_COLS * SNAKE_CELL, SNAKE_ROWS * SNAKE_CELL, FG);
  spr.fillRect(food.x * SNAKE_CELL + 2, SNAKE_Y0 + food.y * SNAKE_CELL + 2, 6, 6, FG);
  for (uint16_t i = 0; i < snakeLen; ++i) spr.fillRect(SNAKE_X0 + snake[i].x * SNAKE_CELL + 1, SNAKE_Y0 + snake[i].y * SNAKE_CELL + 1, SNAKE_CELL - 2, SNAKE_CELL - 2, FG);
  char buf[24]; snprintf(buf, sizeof(buf), "SNAKE %u", snakeScore);
  spr.setTextDatum(TL_DATUM); spr.setTextSize(2); spr.setTextColor(FG, BG); spr.drawString(buf, 6, 8, 1);
  if (state == GAME_OVER) { snprintf(buf, sizeof(buf), "SCORE %u", snakeScore); drawCentered("GAME OVER", buf, "MID RESTART"); }
}

void launchClock(const String &timeStr, const String &dateStr, const String &zoneStr, long epoch) {
  activeMode = MODE_CLOCK; clockDate = dateStr.length() ? dateStr : "date unavailable"; clockZone = zoneStr;
  int h = 0, m = 0, s = epoch > 0 ? epoch % 60 : 0;
  if (timeStr.length() >= 4) { h = timeStr.substring(0, 2).toInt(); m = timeStr.substring(3, 5).toInt(); }
  else if (epoch > 0) { uint32_t e = (uint32_t)epoch % 86400UL; h = e / 3600; m = (e / 60) % 60; s = e % 60; }
  clockBaseSecOfDay = (uint32_t)h * 3600UL + (uint32_t)m * 60UL + s; clockBaseMs = millis();
}

void renderClock() {
  drawHeader("CLOCK");
  uint32_t sec = (clockBaseSecOfDay + (millis() - clockBaseMs) / 1000UL) % 86400UL;
  char t[12]; snprintf(t, sizeof(t), "%02lu:%02lu:%02lu", sec / 3600UL, (sec / 60UL) % 60UL, sec % 60UL);
  spr.setTextDatum(MC_DATUM); spr.setTextColor(FG, BG);
  spr.setTextSize(4); spr.drawString(t, SCREEN_W / 2, 126, 1);
  spr.setTextSize(2); spr.drawString(asciiClean(clockDate), SCREEN_W / 2, 182, 1);
  if (clockZone.length()) spr.drawString(asciiClean(clockZone), SCREEN_W / 2, 210, 1);
}

void renderWeather() {
  drawHeader("WEATHER");
  drawWrapped(weatherText, 14, 72, SCREEN_W - 28, 2, 8);
}

void clearDrawing() { memset(drawGrid, 0, sizeof(drawGrid)); drawGrid[drawY][drawX] = true; }

void updateDraw(bool midEdge, bool setEdge, bool rstEdge) {
  if (midEdge) drawPen = !drawPen;
  if (setEdge || rstEdge) clearDrawing();
  if (millis() - drawLastMoveMs < 85) return;
  int8_t dx = 0, dy = 0;
  if (pressed(JOY_LFT)) dx = -1; else if (pressed(JOY_RHT)) dx = 1;
  if (pressed(JOY_UP)) dy = -1; else if (pressed(JOY_DWN)) dy = 1;
  if (!dx && !dy) return;
  drawLastMoveMs = millis();
  drawX = constrain((int)drawX + dx, 0, DRAW_COLS - 1); drawY = constrain((int)drawY + dy, 0, DRAW_ROWS - 1);
  if (drawPen) drawGrid[drawY][drawX] = true;
}

void renderDraw() {
  drawHeader("DRAW");
  spr.setTextDatum(TL_DATUM); spr.setTextSize(1); spr.setTextColor(FG, BG);
  spr.drawString(drawPen ? "MID pen:ON  SET/RST clear" : "MID pen:OFF SET/RST clear", 4, 34, 1);
  spr.drawRect(0, DRAW_Y0, SCREEN_W, DRAW_ROWS * DRAW_CELL, FG);
  for (uint8_t y = 0; y < DRAW_ROWS; ++y) for (uint8_t x = 0; x < DRAW_COLS; ++x)
    if (drawGrid[y][x]) spr.fillRect(x * DRAW_CELL, DRAW_Y0 + y * DRAW_CELL, DRAW_CELL, DRAW_CELL, FG);
  int16_t px = drawX * DRAW_CELL, py = DRAW_Y0 + drawY * DRAW_CELL;
  spr.drawRect(px, py, DRAW_CELL, DRAW_CELL, drawGrid[drawY][drawX] ? BG : FG);
  spr.drawFastHLine(px, py + DRAW_CELL / 2, DRAW_CELL, drawGrid[drawY][drawX] ? BG : FG);
}

void renderChat() {
  drawHeader("CHAT");
  if (chatPrompt.length()) { spr.setTextDatum(TL_DATUM); spr.setTextSize(1); spr.setTextColor(FG, BG); spr.drawString("Q: " + asciiClean(chatPrompt), 10, 42, 1); }
  if (chatAnswer.length()) drawWrapped(chatAnswer, 12, 78, SCREEN_W - 24, 2, 9);
  else drawCentered("CHAT", "WAITING FOR", "ANSWER");
}

uint32_t timerRemaining() {
  uint32_t elapsed = (millis() - timerStartMs) / 1000UL;
  return elapsed >= timerSeconds ? 0 : timerSeconds - elapsed;
}

void renderTimer() {
  uint32_t rem = timerRemaining();
  bool doneFlash = rem == 0 && ((millis() / 250) & 1);
  if (doneFlash) spr.fillSprite(FG);
  uint16_t ink = doneFlash ? BG : FG, paper = doneFlash ? FG : BG;
  spr.setTextColor(ink, paper); spr.setTextDatum(TC_DATUM); spr.setTextSize(2); spr.drawString("TIMER", SCREEN_W / 2, 8, 1);
  spr.drawFastHLine(10, 32, SCREEN_W - 20, ink);
  spr.setTextDatum(MC_DATUM); spr.setTextSize(2); spr.drawString(asciiClean(timerLabel), SCREEN_W / 2, 82, 1);
  char buf[16]; snprintf(buf, sizeof(buf), "%02lu:%02lu", rem / 60UL, rem % 60UL);
  spr.setTextSize(5); spr.drawString(buf, SCREEN_W / 2, 150, 1);
  spr.setTextSize(2); spr.drawString(rem ? "RUNNING" : "DONE", SCREEN_W / 2, 218, 1);
}

void render() {
  spr.fillSprite(BG);
  if (activeMode == MODE_DINO) renderDino();
  else if (activeMode == MODE_SNAKE) renderSnake();
  else if (activeMode == MODE_CLOCK) renderClock();
  else if (activeMode == MODE_WEATHER) renderWeather();
  else if (activeMode == MODE_DRAW) renderDraw();
  else if (activeMode == MODE_CHAT) renderChat();
  else if (activeMode == MODE_TIMER) renderTimer();
  spr.pushSprite(0, 0);
}

void sendLaunchOk(const char *name) {
  server.send(200, "application/json", String("{\"ok\":true,\"launched\":\"") + name + "\"}");
}

void launchByCue(const String &cue, const String &body) {
  if (cue == "dino") { sendLaunchOk("dino"); activeMode = MODE_DINO; state = PLAYING; resetDino(); }
  else if (cue == "snake") { sendLaunchOk("snake"); activeMode = MODE_SNAKE; state = PLAYING; resetSnake(); }
  else if (cue == "clock") { sendLaunchOk("clock"); launchClock(jsonString(body, "time"), jsonString(body, "date"), jsonString(body, "timezone"), jsonLong(body, "epoch", 0)); }
  else if (cue == "weather") { sendLaunchOk("weather"); activeMode = MODE_WEATHER; String loc = jsonString(body, "location"); weatherText = jsonString(body, "summary"); if (!weatherText.length()) weatherText = (loc.length() ? loc + ": weather unavailable" : "weather unavailable"); }
  else if (cue == "draw") { sendLaunchOk("draw"); activeMode = MODE_DRAW; drawX = DRAW_COLS / 2; drawY = DRAW_ROWS / 2; drawPen = true; clearDrawing(); }
  else if (cue == "chat") { sendLaunchOk("chat"); activeMode = MODE_CHAT; chatPrompt = jsonString(body, "prompt"); chatAnswer = jsonString(body, "answer"); }
  else if (cue == "timer") { sendLaunchOk("timer"); activeMode = MODE_TIMER; timerSeconds = max(1L, jsonLong(body, "seconds", 60)); timerLabel = jsonString(body, "label", "timer"); timerStartMs = millis(); }
  else { server.send(400, "application/json", "{\"ok\":false,\"error\":\"unknown cue\"}"); return; }
  Serial.printf("launched cue=%s\n", cue.c_str()); render();
}

void handleLaunch() {
  String body = server.hasArg("plain") ? server.arg("plain") : "";
  String cue = jsonString(body, "cue"); cue.trim(); cue.toLowerCase();
  Serial.printf("HTTP /launch from %s body=%s cue=%s\n", server.client().remoteIP().toString().c_str(), body.c_str(), cue.c_str());
  launchByCue(cue, body);
}

void setupServer() {
  server.on("/health", HTTP_GET, [] { server.send(200, "application/json", "{\"ok\":true,\"device\":\"esp-lcd-joystick\"}"); });
  server.on("/cues", HTTP_GET, [] { server.send(200, "application/json", "{\"ok\":true,\"cues\":[\"dino\",\"snake\",\"clock\",\"weather\",\"draw\",\"chat\",\"timer\"]}"); });
  server.on("/launch", HTTP_POST, handleLaunch);
  server.onNotFound([] { server.send(404, "application/json", "{\"ok\":false,\"error\":\"not found\"}"); });
  server.begin(); Serial.println("HTTP server listening on port 8765");
}

void serviceNetwork() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiWasConnected) {
      wifiWasConnected = true;
      Serial.printf("WiFi connected, IP=%s\n", WiFi.localIP().toString().c_str());
      Serial.printf("Health: http://%s:8765/health\n", WiFi.localIP().toString().c_str());
      Serial.printf("Cues:   http://%s:8765/cues\n", WiFi.localIP().toString().c_str());
    }
    server.handleClient();
  } else if (millis() - lastWifiRetryMs > 15000) {
    wifiWasConnected = false; lastWifiRetryMs = millis();
    Serial.println("WiFi not connected; retrying"); WiFi.disconnect(); WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
}

void setup() {
  Serial.begin(115200); delay(100);
  pinMode(JOY_UP, INPUT_PULLUP); pinMode(JOY_DWN, INPUT_PULLUP); pinMode(JOY_LFT, INPUT_PULLUP); pinMode(JOY_RHT, INPUT_PULLUP);
  pinMode(JOY_MID, INPUT_PULLUP); pinMode(JOY_SET, INPUT_PULLUP); pinMode(JOY_RST, INPUT_PULLUP);
#ifdef TFT_BL
  pinMode(TFT_BL, OUTPUT); digitalWrite(TFT_BL, TFT_BACKLIGHT_ON);
#endif
  tft.init(); tft.setRotation(0); tft.fillScreen(TFT_WHITE);
  spr.setColorDepth(1);
  if (!spr.createSprite(SCREEN_W, SCREEN_H)) { Serial.printf("sprite alloc failed, free heap=%u\n", ESP.getFreeHeap()); while (true) delay(1000); }
  spr.setBitmapColor(TFT_BLACK, TFT_WHITE);
  Serial.printf("sprite ok, free heap=%u, display=%dx%d\n", ESP.getFreeHeap(), tft.width(), tft.height());
  randomSeed((uint32_t)micros()); resetDino(); resetSnake(); clearDrawing(); render();
  WiFi.mode(WIFI_STA); WiFi.setSleep(false); WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastWifiRetryMs = millis(); Serial.println("WiFi connecting"); setupServer(); lastFrameMs = millis();
}

void loop() {
  serviceNetwork();
  bool upEdge = pressEdge(JOY_UP, dbUp), midEdge = pressEdge(JOY_MID, dbMid);
  bool setEdge = pressEdge(JOY_SET, dbSet), rstEdge = pressEdge(JOY_RST, dbRst);
  pressEdge(JOY_DWN, dbDwn); pressEdge(JOY_LFT, dbLft); pressEdge(JOY_RHT, dbRht);
  bool action = upEdge || midEdge;

  if (activeMode == MODE_DRAW) updateDraw(midEdge, setEdge, rstEdge);

  uint32_t now = millis();
  if (now - lastFrameMs < 33) return;
  lastFrameMs = now;

  if (activeMode == MODE_DINO) {
    if (state == READY && action) { resetDino(); state = PLAYING; dinoVy = DINO_JUMP_VY; dinoOnGround = false; }
    else if (state == PLAYING) { updateDino(action); if (dinoHit()) state = GAME_OVER; }
    else if (state == GAME_OVER && action) { resetDino(); state = PLAYING; }
  } else if (activeMode == MODE_SNAKE) updateSnake(action);

  render();
}

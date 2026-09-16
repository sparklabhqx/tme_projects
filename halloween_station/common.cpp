#include "scenes.h"

using namespace eng;

Scene gScene = SC_MENU;
int hiWhack = 0, hiBat = 0, hiCatch = 0;
uint16_t *bgMenu = nullptr, *bgWhack = nullptr, *bgBat = nullptr, *bgCatch = nullptr;

// ---------------------------------------------------------------- primitives

void fillEllipse(int cx, int cy, int a, int b, uint16_t c) {
  for (int dx = -a; dx <= a; dx++) {
    float t = 1.0f - (float)(dx * dx) / (float)(a * a);
    if (t <= 0) continue;
    int hh = (int)(b * sqrtf(t));
    vline(cx + dx, cy - hh, cy + hh, c);
  }
}

void starsCompose(int count, uint32_t seed) {
  uint32_t s = seed | 1;
  for (int i = 0; i < count; i++) {
    s ^= s << 13; s ^= s >> 17; s ^= s << 5;
    int x = s % SCREEN_W;
    s ^= s << 13; s ^= s >> 17; s ^= s << 5;
    int y = s % (SCREEN_H * 3 / 4);
    s ^= s << 13; s ^= s >> 17; s ^= s << 5;
    int b = 120 + (s % 136);
    uint16_t c = rgb565(b, b, (b * 4) / 5);
    px(x, y, c);
    if ((s & 7) == 0) {  // a few bigger twinkles
      px(x + 1, y, c); px(x - 1, y, c); px(x, y + 1, c); px(x, y - 1, c);
    }
  }
}

void hillsCompose(uint16_t color, int base, int amp1, int per1, int amp2, int per2, int phase) {
  for (int x = 0; x < SCREEN_W; x++) {
    int y = base
          + (int)(amp1 * sinf((x + phase) * 2.0f * PI / per1))
          + (int)(amp2 * sinf((x * 1.7f + phase * 2) * 2.0f * PI / per2));
    vline(x, y, SCREEN_H - 1, color);
  }
}

// ---------------------------------------------------------------- back button

void drawBackButton() {
  bool hot = touch.down && touch.x < 78 && touch.y < 62;
  dimRect(0, 0, 76, 60, hot ? 210 : 140, rgb565(20, 10, 30));
  blit(spr_skull, 15, 5);
  textCenter(font_small, "BACK", 38, 52, ARGB(255, 210, 190, 230));
}

bool backTapped() {
  return touch.pressed && touch.x < 78 && touch.y < 62;
}

// ---------------------------------------------------------------- game over

static float goT = 0;
static bool goActive = false;
static bool goNewBest = false;

void gameOverReset() { goT = 0; goActive = false; goNewBest = false; }

int gameOverTick(const char* title, int score, int* best) {
  if (!goActive) {
    goActive = true;
    goNewBest = score > *best;
    if (goNewBest) *best = score;
    // confetti burst of embers
    for (int i = 0; i < 40; i++) {
      float a = rndf() * 6.28f, sp = 80 + rndf() * 260;
      spawnParticle(P_SPARK, SCREEN_W / 2, SCREEN_H / 2 - 40,
                    cosf(a) * sp, sinf(a) * sp - 120, 1.0f + rndf(),
                    goNewBest ? rgb565(255, 220, 90) : rgb565(255, 140, 40));
    }
  }
  goT += dt;

  float t = goT < 0.35f ? goT / 0.35f : 1.0f;
  int panelW = 520, panelH = 300;
  int ph = (int)(panelH * (0.6f + 0.4f * t));
  int px0 = SCREEN_W / 2 - panelW / 2, py0 = SCREEN_H / 2 - ph / 2;

  dimRect(0, 0, SCREEN_W, SCREEN_H, (uint8_t)(190 * t), rgb565(8, 2, 16));
  fillRoundRect(px0, py0, panelW, ph, 18, rgb565(28, 14, 44));
  fillRoundRect(px0 + 4, py0 + 4, panelW - 8, ph - 8, 15, rgb565(46, 24, 70));
  fillRoundRect(px0 + 8, py0 + 8, panelW - 16, ph - 16, 12, rgb565(22, 10, 36));

  if (t < 1.0f) return 0;

  int cx = SCREEN_W / 2;
  textCenter(font_big, title, cx, py0 + 66, ARGB(255, 255, 150, 40));

  char buf[40];
  snprintf(buf, sizeof(buf), "SCORE  %d", score);
  textCenter(font_hud, buf, cx, py0 + 116, ARGB(255, 240, 235, 255));

  if (goNewBest) {
    float pulse = 0.65f + 0.35f * sinf(goT * 7.0f);
    textCenter(font_hud, "NEW BEST", cx, py0 + 156, ARGB(255, (uint8_t)(255 * pulse), (uint8_t)(220 * pulse), 60));
  } else {
    snprintf(buf, sizeof(buf), "BEST  %d", *best);
    textCenter(font_hud, buf, cx, py0 + 156, ARGB(255, 170, 150, 200));
  }

  // buttons
  int bw = 200, bh = 64, by = py0 + panelH - 96;
  int b1 = cx - bw - 14, b2 = cx + 14;
  bool h1 = touch.down && touch.x >= b1 && touch.x < b1 + bw && touch.y >= by && touch.y < by + bh;
  bool h2 = touch.down && touch.x >= b2 && touch.x < b2 + bw && touch.y >= by && touch.y < by + bh;
  fillRoundRect(b1, by, bw, bh, 14, h1 ? rgb565(255, 160, 40) : rgb565(190, 95, 12));
  fillRoundRect(b2, by, bw, bh, 14, h2 ? rgb565(150, 90, 220) : rgb565(96, 52, 150));
  textCenter(font_hud, "AGAIN", b1 + bw / 2, by + 42, ARGB(255, 30, 12, 4));
  textCenter(font_hud, "MENU", b2 + bw / 2, by + 42, ARGB(255, 240, 230, 255));

  if (touch.pressed) {
    if (h1) { gameOverReset(); return 1; }
    if (h2) { gameOverReset(); return 2; }
  }
  return 0;
}

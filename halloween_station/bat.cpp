#include "scenes.h"

using namespace eng;

// ---------------------------------------------------------------- constants

static const int GROUND_Y = 424;
static const float GRAV = 1500.0f;
static const float FLAP = -455.0f;
static const int BAT_W = 100, BAT_H = 68;

struct Gate { float x; int gapY, gapH; bool scored; int8_t candy; bool candyGot; };
static Gate gates[4];
static float bx, by, vy;
static float scrollX, speed, gameT, deadT, flapT, introT;
static int score;
static bool dead, started;
static uint16_t groundSeed;

// ---------------------------------------------------------------- background

static void composeBatBg() {
  layerTarget(bgBat);
  layerVGrad(rgb565(8, 4, 24), rgb565(52, 20, 60), 0, 260);
  layerVGrad(rgb565(52, 20, 60), rgb565(96, 40, 40), 260, SCREEN_H);
  starsCompose(210, 0xC0FFEE);

  layerGlow(300, 96, 130, 80, 72, 44);
  blit(spr_moon, 210, 0);

  blitTint(spr_cloud0, 40, 120, ARGB(80, 110, 96, 150));
  blitTint(spr_cloud1, 470, 60, ARGB(95, 120, 100, 155));
  blitTint(spr_cloud0, 640, 170, ARGB(70, 100, 88, 140));

  // distant skyline: hills + a haunted-house silhouette + bare trees
  hillsCompose(rgb565(26, 12, 34), 300, 18, 700, 9, 210, 40);
  blitTint(spr_tree, 60, 118, ARGB(255, 16, 8, 24));
  blitTint(spr_tree, 520, 150, ARGB(255, 14, 7, 20));

  // haunted house
  {
    int hx = 330, hy = 250;
    uint16_t dark = rgb565(18, 9, 26);
    fillRect(hx, hy, 120, 100, dark);
    for (int i = 0; i < 46; i++)  // roof
      vline(hx - 12 + i * 3, hy - 46 + abs(i - 23) * 2, hy, dark);
    fillRect(hx + 82, hy - 76, 26, 78, dark);     // tower
    for (int i = 0; i < 14; i++)
      vline(hx + 82 + i * 2, hy - 76 - (7 - abs(i - 7)) * 4, hy - 70, dark);
    fillRect(hx + 18, hy + 26, 20, 24, rgb565(200, 150, 40));  // lit windows
    fillRect(hx + 70, hy + 26, 20, 24, rgb565(200, 150, 40));
    fillRect(hx + 46, hy + 62, 24, 38, rgb565(120, 70, 20));
  }

  // distant fence row
  for (int x = -4; x < SCREEN_W; x += 22)
    fillRect(x, 330, 7, 26, rgb565(30, 16, 28));

  // ground band (static part; scrolling detail is drawn per frame)
  fillRect(0, GROUND_Y, SCREEN_W, SCREEN_H - GROUND_Y, rgb565(26, 14, 22));
  layerTarget(nullptr);
}

// ---------------------------------------------------------------- gates

static void resetGate(Gate& g, float x) {
  g.x = x;
  g.gapH = 190 - (int)min(48.0f, gameT * 1.6f);
  g.gapY = rndi(70, GROUND_Y - g.gapH - 40);
  g.scored = false;
  g.candy = rndf() < 0.45f ? rndi(0, 2) : -1;
  g.candyGot = false;
}

void batEnter() {
  bx = 170; by = 210; vy = 0;
  scrollX = 0; speed = 210; gameT = 0; deadT = 0; flapT = 0; introT = 0;
  score = 0; dead = false; started = false;
  for (int i = 0; i < 4; i++) resetGate(gates[i], 520 + i * 260);
  clearParticles();
  gameOverReset();
  groundSeed = 0x77;
}

// ---------------------------------------------------------------- pillar art

static void drawPillar(int x, int y0, int y1) {
  const int W = 76;
  uint16_t body = rgb565(112, 118, 132);
  uint16_t dark = rgb565(58, 62, 74);
  uint16_t lite = rgb565(150, 156, 172);
  fillRect(x, y0, W, y1 - y0, body);
  fillRect(x, y0, 10, y1 - y0, lite);          // lit edge
  fillRect(x + W - 12, y0, 12, y1 - y0, dark); // shaded edge
  // block seams
  for (int y = y0 + 26; y < y1 - 6; y += 34)
    fillRect(x + 2, y, W - 4, 3, dark);
  // moss
  for (int y = y0 + 8; y < y1 - 8; y += 46)
    fillRect(x + 4, y, 8, 18, rgb565(56, 92, 48));
}

static void drawCap(int x, int y, bool down) {
  const int W = 76;
  uint16_t body = rgb565(126, 132, 146);
  uint16_t dark = rgb565(58, 62, 74);
  int capH = 26;
  int cy = down ? y : y - capH;
  fillRect(x - 10, cy, W + 20, capH, body);
  fillRect(x - 10, down ? cy + capH - 5 : cy, W + 20, 5, dark);
  // little pointed finial
  int fy = down ? cy + capH : cy - 16;
  for (int i = 0; i < 16; i++) {
    int hw = down ? (16 - i) : i;      // tapers away from the cap either way
    fillRect(x + W / 2 - hw / 2, fy + i, max(1, hw), 1, body);
  }
}

// ---------------------------------------------------------------- frame

void batTick() {
  if (!dead) gameT += dt;

  // ---- input ----
  if (!dead && touch.pressed && !(touch.x < 78 && touch.y < 62)) {
    started = true;
    vy = FLAP;
    flapT = 0.22f;
    for (int i = 0; i < 5; i++)
      spawnParticle(P_SPARK, bx + 20, by + 50, rndf() * 120 - 60, 40 + rndf() * 120,
                    0.45f, rgb565(150, 110, 220));
  }

  // ---- physics ----
  if (started && !dead) {
    vy += GRAV * dt;
    if (vy > 760) vy = 760;
    by += vy * dt;
    speed = 210 + min(150.0f, gameT * 4.2f);
    scrollX += speed * dt;
    if (by < -10) { by = -10; vy = 0; }
  } else if (!started) {
    by = 210 + sinf(gameT * 3.0f) * 14;
    scrollX += 40 * dt;
  } else {
    vy += GRAV * dt;
    by += vy * dt;
    deadT += dt;
  }
  if (flapT > 0) flapT -= dt;

  // ---- world scroll ----
  layerFromScroll(bgBat, (int)(scrollX * 0.35f));

  // scrolling ground texture
  {
    int gs = (int)scrollX;
    for (int x = 0; x < SCREEN_W; x++) {
      int wx = (x + gs) % 4000;
      uint32_t s = (uint32_t)wx * 2654435761u;
      int y = GROUND_Y + 2 + (int)((s >> 28) & 3);
      vline(x, y, y + 2, rgb565(58, 34, 40));
      if (((s >> 20) & 31) == 0) vline(x, GROUND_Y + 8, GROUND_Y + 14, rgb565(40, 24, 32));
    }
    fillRect(0, GROUND_Y - 4, SCREEN_W, 5, rgb565(78, 46, 52));
  }

  // ---- gates ----
  if (started && !dead) {
    for (auto& g : gates) {
      g.x -= speed * dt;
      if (g.x < -110) {
        float maxx = -1e9f;
        for (auto& o : gates) maxx = max(maxx, o.x);
        resetGate(g, maxx + 250 - min(60.0f, gameT * 1.2f));
      }
    }
  }

  for (auto& g : gates) {
    int gx = (int)g.x;
    if (gx > SCREEN_W + 20 || gx < -110) continue;
    drawPillar(gx, 0, g.gapY);
    drawCap(gx, g.gapY, true);
    drawPillar(gx, g.gapY + g.gapH, GROUND_Y);
    drawCap(gx, g.gapY + g.gapH, false);
    // candy pickup floating in the gap
    if (g.candy >= 0 && !g.candyGot) {
      const Sprite* cs = g.candy == 0 ? &spr_candycorn
                       : (g.candy == 1 ? &spr_candywrap : &spr_eyeball);
      int cy = g.gapY + g.gapH / 2 + (int)(8 * sinf(gameT * 4 + gx));
      blit(*cs, gx + 38 - cs->lw / 2, cy - cs->lh / 2);
    }
  }

  // ---- collisions ----
  if (started && !dead) {
    int hx0 = (int)bx + 26, hx1 = (int)bx + BAT_W - 26;
    int hy0 = (int)by + 18, hy1 = (int)by + BAT_H - 12;
    for (auto& g : gates) {
      int gx0 = (int)g.x - 10, gx1 = (int)g.x + 86;
      if (hx1 > gx0 && hx0 < gx1) {
        if (hy0 < g.gapY + 4 || hy1 > g.gapY + g.gapH - 4) {
          dead = true;
          led(220, 30, 30);
          for (int i = 0; i < 26; i++)
            spawnParticle(P_SPARK, bx + 50, by + 34, rndf() * 400 - 200,
                          rndf() * 400 - 220, 0.9f, rgb565(190, 150, 255));
        }
      }
      if (!g.scored && g.x + 86 < bx) { g.scored = true; score++; led(60, 40, 180); }
      if (g.candy >= 0 && !g.candyGot) {
        int cx = (int)g.x + 38, cy = g.gapY + g.gapH / 2;
        if (fabsf(cx - (bx + 50)) < 46 && fabsf(cy - (by + 34)) < 44) {
          g.candyGot = true; score += 3;
          led(255, 200, 40);
          for (int i = 0; i < 12; i++)
            spawnParticle(P_SPARK, cx, cy, rndf() * 300 - 150, rndf() * 300 - 150,
                          0.6f, rgb565(255, 215, 90));
        }
      }
    }
    if (by + BAT_H - 12 > GROUND_Y) { dead = true; by = GROUND_Y - BAT_H + 12; led(220, 30, 30); }
  }

  updateDrawParticles();

  // ---- bat ----
  {
    const Sprite* s;
    if (dead) s = &spr_bat2;
    else if (flapT > 0.11f) s = &spr_bat2;
    else if (flapT > 0) s = &spr_bat1;
    else s = vy < -40 ? &spr_bat1 : &spr_bat0;
    blit(*s, (int)bx, (int)by);
    // motion trail
    if (started && !dead && (frameNo & 1))
      spawnParticle(P_DOT, bx + 12, by + 34 + rndf() * 8, -speed * 0.35f, 10,
                    0.35f, rgb565(80, 60, 130));
  }

  // ---- HUD ----
  if (started) {
    char buf[16];
    snprintf(buf, sizeof(buf), "%d", score);
    // outline for legibility over busy art
    for (int dx = -2; dx <= 2; dx += 2)
      for (int dy = -2; dy <= 2; dy += 2)
        if (dx || dy) textCenter(font_big, buf, SCREEN_W / 2 + dx, 66 + dy, ARGB(230, 10, 4, 18));
    textCenter(font_big, buf, SCREEN_W / 2, 66, ARGB(255, 255, 225, 120));
  } else {
    float k = 0.6f + 0.4f * sinf(gameT * 4.0f);
    textCenter(font_big, "TAP TO FLAP", SCREEN_W / 2, 120,
               ARGB((uint8_t)(255 * k), 255, 210, 90));
    textCenter(font_small, "AVOID THE STONES  GRAB THE TREATS", SCREEN_W / 2, 158,
               ARGB(220, 220, 200, 255));
  }

  drawBackButton();
  if (backTapped()) { gScene = SC_MENU; return; }

  if (dead && deadT > 0.6f) {
    int r = gameOverTick("SPLAT", score, &hiBat);
    if (r == 1) batEnter();
    else if (r == 2) gScene = SC_MENU;
  }
  if (!dead) led(24, 10, 40);
}

void batComposeBg() { composeBatBg(); }

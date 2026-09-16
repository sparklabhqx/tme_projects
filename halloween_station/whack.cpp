#include "scenes.h"

using namespace eng;

// ---------------------------------------------------------------- layout

struct Hole { int cx, cy; };
static const Hole holes[6] = {
  { 150, 258 }, { 400, 250 }, { 650, 258 },
  { 158, 402 }, { 400, 412 }, { 642, 402 },
};
static const int MRX = 94, MRY = 34;

enum PMode : uint8_t { H_IDLE, H_RISE, H_UP, H_FALL, H_HIT };
struct HoleState {
  PMode mode; bool ghost; float p, tmr, upTime; uint8_t splat;
};
static HoleState hs[6];

static float gameT, spawnT, spawnGap, shakeT, flashT;
static int score, combo, bestCombo;
static float timeLeft;
static bool over;
static float introT;
static float redT;

// ---------------------------------------------------------------- background

static void composeWhackBg() {
  layerTarget(bgWhack);
  layerVGrad(rgb565(12, 6, 30), rgb565(70, 28, 52), 0, 210);
  layerVGrad(rgb565(70, 28, 52), rgb565(36, 16, 34), 210, SCREEN_H);
  starsCompose(140, 0x51DE22);

  layerGlow(120, 70, 96, 80, 70, 40);
  blit(spr_moon, 74, 12);            // moon top-left, out of the HUD's way

  blitTint(spr_cloud1, 180, 40, ARGB(110, 110, 96, 140));
  blitTint(spr_cloud0, 520, 26, ARGB(90, 100, 88, 130));

  hillsCompose(rgb565(30, 14, 36), 186, 12, 520, 6, 170, 60);
  blitTint(spr_tree, 596, 14, ARGB(255, 14, 7, 20));
  blitTint(spr_tree, -30, 6, ARGB(255, 18, 9, 24));

  // ground
  fillRect(0, 196, SCREEN_W, SCREEN_H - 196, rgb565(30, 16, 26));
  for (int y = 196; y < SCREEN_H; y += 3) {   // subtle ground banding = depth
    int shade = 30 + (y - 196) / 9;
    fillRect(0, y, SCREEN_W, 2, rgb565(shade, shade / 2 + 6, shade - 6));
  }

  // tombstones behind the top row
  blit(spr_grave0, 258, 128);
  blit(spr_grave2, 480, 120);
  blit(spr_grave1, 40, 132);

  // picket fence along the horizon
  for (int x = 0; x < SCREEN_W; x += 26) {
    fillRect(x, 168, 9, 34, rgb565(58, 40, 34));
    fillRect(x + 1, 166, 7, 4, rgb565(78, 56, 44));
  }
  fillRect(0, 176, SCREEN_W, 4, rgb565(50, 34, 28));
  fillRect(0, 192, SCREEN_W, 4, rgb565(50, 34, 28));

  // holes: dark pits with a rim of loose dirt
  for (const auto& h : holes) {
    fillEllipse(h.cx, h.cy, MRX - 6, MRY - 6, rgb565(14, 7, 12));
    fillEllipse(h.cx, h.cy - 3, MRX - 14, MRY - 12, rgb565(6, 3, 6));
  }
  layerTarget(nullptr);
}

static void drawMound(const Hole& h) {
  blit(spr_mound, h.cx - spr_mound.lw / 2, h.cy - 40);
}

// ---------------------------------------------------------------- lifecycle

void whackEnter() {
  for (auto& h : hs) h = { H_IDLE, false, 0, 0, 0, 0 };
  gameT = 0; spawnT = 0; spawnGap = 0.85f; shakeT = 0; flashT = 0; redT = 0;
  score = 0; combo = 1; bestCombo = 1; timeLeft = 45.0f; over = false; introT = 0;
  clearParticles();
  gameOverReset();
}

static void spawnOne() {
  int free_[6], n = 0;
  for (int i = 0; i < 6; i++) if (hs[i].mode == H_IDLE) free_[n++] = i;
  if (!n) return;
  int i = free_[rndi(0, n - 1)];
  float diff = min(1.0f, gameT / 35.0f);
  hs[i].mode = H_RISE;
  hs[i].ghost = rndf() < (0.14f + 0.16f * diff);
  hs[i].p = 0; hs[i].tmr = 0;
  hs[i].upTime = 1.25f - 0.65f * diff + rndf() * 0.3f;
}

void whackTick() {
  layerFrom(bgWhack);

  if (introT < 3.2f && !over) {
    introT += dt;
  } else if (!over) {
    gameT += dt;
    timeLeft -= dt;
    if (timeLeft <= 0) { timeLeft = 0; over = true; }
    spawnT += dt;
    spawnGap = 0.95f - 0.5f * min(1.0f, gameT / 35.0f);
    if (spawnT > spawnGap) { spawnT = 0; spawnOne(); }
  }

  // screen shake decay
  if (shakeT > 0) {
    shakeT -= dt;
    int mag = (int)(9 * (shakeT / 0.22f));
    shakeX = rndi(-mag, mag); shakeY = rndi(-mag, mag);
  } else { shakeX = 0; shakeY = 0; }

  bool hitThisFrame = false;

  for (int i = 0; i < 6; i++) {
    HoleState& s = hs[i];
    const Hole& h = holes[i];
    s.tmr += dt;

    switch (s.mode) {
      case H_RISE:
        s.p += dt * 4.2f;
        if (s.p >= 1.0f) { s.p = 1.0f; s.mode = H_UP; s.tmr = 0; }
        break;
      case H_UP:
        if (s.tmr > s.upTime) { s.mode = H_FALL; }
        break;
      case H_FALL:
        s.p -= dt * 3.4f;
        if (s.p <= 0) { s.p = 0; s.mode = H_IDLE; s.tmr = 0;
                        if (!s.ghost) combo = 1; }
        break;
      case H_HIT:
        if (s.tmr > 0.42f) { s.mode = H_IDLE; s.p = 0; s.tmr = 0; }
        break;
      default: break;
    }

    // ---- draw the critter, clipped so it emerges from behind the dirt ----
    if (s.mode == H_RISE || s.mode == H_UP || s.mode == H_FALL) {
      int botY = h.cy + 18;
      float ease = s.mode == H_RISE ? 1.0f - (1.0f - s.p) * (1.0f - s.p) : s.p;
      setClip(0, 0, SCREEN_W, h.cy + 12);
      if (s.ghost) {
        int gy = botY - (int)(ease * 130);
        blitA((frameNo & 16) ? spr_ghost0 : spr_ghost1, h.cx - 52, gy, 225);
      } else {
        int py = botY - (int)(ease * 122);
        const Sprite* sp;
        if (s.mode == H_RISE && s.p < 0.75f) sp = &spr_pumpkin_stretch;
        else sp = (frameNo & 8) ? &spr_pumpkin1 : &spr_pumpkin0;
        blit(*sp, h.cx - sp->lw / 2, py);
        if (s.mode == H_UP && (frameNo % 9) == (uint32_t)i)
          spawnParticle(P_EMBER, h.cx + rndi(-24, 24), py + 8, rndf() * 16 - 8,
                        -35 - rndf() * 30, 1.0f, rgb565(255, 160, 40), rndi(0, 200));
      }
      clearClip();

      // ---- hit test ----
      if (touch.pressed && !hitThisFrame) {
        int top = botY - (int)(ease * 122);
        if (touch.x > h.cx - 70 && touch.x < h.cx + 70 &&
            touch.y > top - 6 && touch.y < h.cy + 22) {
          hitThisFrame = true;
          s.mode = H_HIT; s.tmr = 0; s.splat = rndi(0, 1);
          int sy = top + 30;
          if (s.ghost) {
            combo = 1; timeLeft = max(0.0f, timeLeft - 3.0f); redT = 0.45f;
            led(220, 20, 20);
            for (int k = 0; k < 18; k++)
              spawnParticle(P_SPARK, h.cx, sy, rndf() * 300 - 150, rndf() * -220 - 40,
                            0.7f, rgb565(200, 200, 255));
          } else {
            score += 10 * combo;
            if (combo < 9) combo++;
            if (combo > bestCombo) bestCombo = combo;
            shakeT = 0.22f;
            led(255, 110, 0);
            for (int k = 0; k < 10; k++)
              spawnParticle(P_CHUNK, h.cx - 10, sy, rndf() * 420 - 210, rndf() * -320 - 90,
                            1.3f, 0, rndi(0, 2));
            for (int k = 0; k < 14; k++)
              spawnParticle(P_SPARK, h.cx, sy, rndf() * 340 - 170, rndf() * -260 - 40,
                            0.6f, rgb565(255, 200, 80));
          }
        }
      }
    }

    // ---- splat ----
    if (s.mode == H_HIT && !s.ghost) {
      const Sprite& sp = s.splat ? spr_splat1 : spr_splat0;
      int a = (int)(255 * (1.0f - s.tmr / 0.42f));
      blitA(sp, h.cx - sp.lw / 2, h.cy - 40, (uint8_t)max(0, a));
    }

    drawMound(h);
  }

  updateDrawParticles();

  // ---------------------------------------------------------- HUD
  dimRect(0, 0, SCREEN_W, 64, 170, rgb565(10, 4, 18));
  char buf[40];
  snprintf(buf, sizeof(buf), "%d", score);
  text(font_big, buf, 92, 46, ARGB(255, 255, 190, 50));

  if (combo > 1) {
    snprintf(buf, sizeof(buf), "X%d", combo);
    float k = 0.7f + 0.3f * sinf(gameT * 12.0f);
    text(font_hud, buf, 92 + textWidth(font_big, "0000") + 10, 42,
         ARGB(255, (uint8_t)(255 * k), (uint8_t)(120 * k), 255));
  }

  // time bar
  int barW = 300, barX = SCREEN_W - barW - 20;
  fillRoundRect(barX, 18, barW, 26, 8, rgb565(40, 20, 30));
  float frac = timeLeft / 45.0f;
  uint16_t tc = frac > 0.33f ? rgb565(120, 220, 90) : rgb565(240, 70, 50);
  if (frac > 0.01f) fillRoundRect(barX + 3, 21, (int)((barW - 6) * frac), 20, 6, tc);
  snprintf(buf, sizeof(buf), "%d", (int)ceilf(timeLeft));
  textCenter(font_small, buf, barX - 26, 42, ARGB(255, 230, 220, 255));

  drawBackButton();
  if (backTapped()) { gScene = SC_MENU; return; }

  // ---------------------------------------------------------- overlays
  if (redT > 0) {
    redT -= dt;
    dimRect(0, 0, SCREEN_W, SCREEN_H, (uint8_t)(130 * (redT / 0.45f)), rgb565(255, 20, 20));
  } else if (!over) {
    led(30, 8, 26);
  }

  if (introT < 3.2f && !over) {
    dimRect(0, 0, SCREEN_W, SCREEN_H, 120, rgb565(6, 2, 12));
    int n = 3 - (int)introT;
    if (n > 0) {
      snprintf(buf, sizeof(buf), "%d", n);
      float f = introT - (int)introT;
      textCenter(font_big, buf, SCREEN_W / 2, 250 - (int)(f * 14),
                 ARGB((uint8_t)(255 * (1.0f - f * 0.6f)), 255, 170, 40));
    }
    textCenter(font_hud, n > 0 ? "GET READY" : "SMASH", SCREEN_W / 2, 320,
               ARGB(255, 250, 240, 255));
  }

  if (over) {
    shakeX = 0; shakeY = 0;
    led(120, 20, 60);
    int r = gameOverTick("TIMES UP", score, &hiWhack);
    if (r == 1) whackEnter();
    else if (r == 2) gScene = SC_MENU;
  }
}

void whackComposeBg() { composeWhackBg(); }

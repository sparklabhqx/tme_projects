#include "scenes.h"

using namespace eng;

// ---------------------------------------------------------------- state

struct Drop {
  bool alive; uint8_t kind;      // 0 candycorn, 1 wrapper, 2 eyeball, 3 skull(bad)
  float x, y, vy, spin;
};
static Drop drops[14];

struct Pop { float x, y, life; char txt[8]; uint16_t col; };
static Pop pops[6];

static float catcherX, catcherVX;
static float gameT, spawnT, spawnGap, flashT, shakeT, witchT, squashT;
static int score, lives, streak;
static bool over;

static const int CAU_W = 172, CAU_H = 132;
static const int CAU_Y = SCREEN_H - 150;

// ---------------------------------------------------------------- background

static void composeCatchBg() {
  layerTarget(bgCatch);
  layerVGrad(rgb565(16, 4, 34), rgb565(58, 16, 70), 0, 240);
  layerVGrad(rgb565(58, 16, 70), rgb565(30, 10, 40), 240, SCREEN_H);
  starsCompose(160, 0x1337BEE);

  // witch-hut interior vibe: hanging lanterns + shelf silhouettes
  for (int i = 0; i < 4; i++) {
    int x = 110 + i * 200;
    vline(x, 0, 60 + (i % 2) * 26, rgb565(50, 30, 60));
    int ly = 60 + (i % 2) * 26;
    fillRect(x - 10, ly, 20, 26, rgb565(70, 46, 30));
    fillRect(x - 7, ly + 3, 14, 20, rgb565(255, 180, 60));
    layerGlow(x, ly + 13, 64, 120, 70, 10);
  }

  hillsCompose(rgb565(24, 8, 34), 352, 10, 480, 5, 160, 90);
  blitTint(spr_tree, 620, 90, ARGB(255, 14, 6, 22));
  blitTint(spr_tree, -40, 120, ARGB(255, 16, 7, 24));

  // stone floor
  fillRect(0, 400, SCREEN_W, SCREEN_H - 400, rgb565(38, 20, 42));
  for (int y = 404; y < SCREEN_H; y += 22) {
    fillRect(0, y, SCREEN_W, 2, rgb565(26, 12, 30));
    for (int x = ((y / 22) & 1) ? 0 : 40; x < SCREEN_W; x += 80)
      fillRect(x, y, 2, 22, rgb565(26, 12, 30));
  }
  // green glow pooling on the floor under the cauldron area
  layerGlow(SCREEN_W / 2, 470, 240, 20, 90, 30);
  layerTarget(nullptr);
}

// ---------------------------------------------------------------- helpers

static void addPop(float x, float y, const char* t, uint16_t col) {
  for (auto& p : pops) {
    if (p.life <= 0) {
      p.x = x; p.y = y; p.life = 0.9f; p.col = col;
      strncpy(p.txt, t, sizeof(p.txt) - 1); p.txt[sizeof(p.txt) - 1] = 0;
      return;
    }
  }
}

static const Sprite* dropSprite(uint8_t k) {
  switch (k) {
    case 0: return &spr_candycorn;
    case 1: return &spr_candywrap;
    case 2: return &spr_eyeball;
    default: return &spr_skull;
  }
}

void catchEnter() {
  for (auto& d : drops) d.alive = false;
  for (auto& p : pops) p.life = 0;
  catcherX = SCREEN_W / 2; catcherVX = 0;
  gameT = 0; spawnT = 0; spawnGap = 1.0f; flashT = 0; shakeT = 0; witchT = 4; squashT = 0;
  score = 0; lives = 3; streak = 0; over = false;
  clearParticles();
  gameOverReset();
}

static void spawnDrop() {
  for (auto& d : drops) {
    if (d.alive) continue;
    d.alive = true;
    float diff = min(1.0f, gameT / 45.0f);
    d.kind = rndf() < (0.16f + 0.17f * diff) ? 3 : rndi(0, 2);
    d.x = rndi(60, SCREEN_W - 60);
    d.y = -40;
    d.vy = 150 + rndf() * 90 + diff * 190;
    d.spin = rndf() * 6.28f;
    return;
  }
}

// ---------------------------------------------------------------- frame

void catchTick() {
  if (!over) gameT += dt;
  layerFrom(bgCatch);

  if (shakeT > 0) {
    shakeT -= dt;
    int m = (int)(8 * (shakeT / 0.25f));
    shakeX = rndi(-m, m); shakeY = rndi(-m, m);
  } else { shakeX = 0; shakeY = 0; }

  // ---- cauldron follows the finger ----
  if (!over && touch.down && touch.y > 70) {
    float target = touch.x;
    float d = target - catcherX;
    catcherX += d * min(1.0f, dt * 14.0f);
  }
  catcherX = constrain(catcherX, CAU_W / 2.0f, SCREEN_W - CAU_W / 2.0f);

  // ---- witch fly-by dropping loot ----
  witchT += dt;
  if (witchT > 12.0f) witchT = 0;
  if (witchT < 6.0f) {
    float p = witchT / 6.0f;
    int wx = (int)(-160 + p * (SCREEN_W + 320));
    int wy = 42 + (int)(10 * sinf(witchT * 2.5f));
    blitTint(((int)(witchT * 6) & 1) ? spr_witch0 : spr_witch1, wx, wy, ARGB(210, 18, 8, 26));
  }

  // ---- spawn ----
  if (!over) {
    spawnT += dt;
    spawnGap = 0.95f - 0.55f * min(1.0f, gameT / 45.0f);
    if (spawnT > spawnGap) { spawnT = 0; spawnDrop(); if (rndf() < 0.25f) spawnDrop(); }
  }

  // ---- drops ----
  int rimY = CAU_Y + 30;
  for (auto& d : drops) {
    if (!d.alive) continue;
    if (!over) { d.vy += 240 * dt; d.y += d.vy * dt; }
    const Sprite* s = dropSprite(d.kind);
    // trailing glow for treats
    if (d.kind != 3 && (frameNo & 3) == 0)
      spawnParticle(P_DOT, d.x, d.y - 6, 0, -20, 0.35f, rgb565(120, 90, 160));
    blit(*s, (int)d.x - s->lw / 2, (int)d.y - s->lh / 2);

    // catch test against the cauldron mouth
    if (d.y > rimY - 12 && d.y < rimY + 40 &&
        fabsf(d.x - catcherX) < CAU_W * 0.40f) {
      d.alive = false;
      squashT = 0.18f;
      if (d.kind == 3) {
        lives--; streak = 0; flashT = 0.4f; shakeT = 0.25f;
        led(230, 20, 20);
        addPop(d.x, rimY - 20, "OUCH", rgb565(255, 70, 60));
        for (int i = 0; i < 20; i++)
          spawnParticle(P_SPARK, d.x, rimY, rndf() * 400 - 200, rndf() * -300 - 60,
                        0.8f, rgb565(240, 240, 250));
        if (lives <= 0) over = true;
      } else {
        streak++;
        int pts = 5 * (1 + min(4, streak / 4));
        score += pts;
        led(60, 220, 60);
        char b[8]; snprintf(b, sizeof(b), "+%d", pts);
        addPop(d.x, rimY - 20, b, rgb565(150, 255, 120));
        for (int i = 0; i < 14; i++)
          spawnParticle(P_SPARK, d.x, rimY, rndf() * 300 - 150, rndf() * -280 - 70,
                        0.75f, rgb565(120, 240, 90));
      }
    } else if (d.y > SCREEN_H + 40) {
      d.alive = false;
      if (d.kind != 3 && !over) {
        streak = 0;
        addPop(d.x, SCREEN_H - 60, "MISS", rgb565(255, 140, 60));
      }
    }
  }

  // ---- cauldron ----
  {
    const Sprite& cs = (squashT > 0) ? spr_cauldron1 : spr_cauldron0;
    if (squashT > 0) squashT -= dt;
    int cx = (int)catcherX - CAU_W / 2;
    int cy = CAU_Y + (squashT > 0 ? 4 : 0);
    blitTint(spr_glow_l, (int)catcherX - 150, cy + 34 - 150, ARGB(120, 60, 230, 80));
    blit(cs, cx, cy);
    // brew bubbles rising out of the pot
    if ((frameNo % 5) == 0)
      spawnParticle(P_DOT, catcherX + rndi(-52, 52), cy + 30, rndf() * 24 - 12,
                    -40 - rndf() * 40, 0.9f, rgb565(140, 240, 110));
  }

  updateDrawParticles();

  // ---- score pops ----
  for (auto& p : pops) {
    if (p.life <= 0) continue;
    p.life -= dt;
    p.y -= 46 * dt;
    uint8_t a = (uint8_t)(255 * min(1.0f, p.life / 0.5f));
    textCenter(font_hud, p.txt, (int)p.x, (int)p.y,
               ARGB(a, (p.col >> 11) << 3, ((p.col >> 5) & 0x3F) << 2, (p.col & 0x1F) << 3));
  }

  // ---- HUD ----
  dimRect(0, 0, SCREEN_W, 64, 165, rgb565(10, 4, 18));
  char buf[32];
  snprintf(buf, sizeof(buf), "%d", score);
  text(font_big, buf, 92, 46, ARGB(255, 180, 255, 140));
  if (streak >= 4) {
    snprintf(buf, sizeof(buf), "STREAK %d", streak);
    text(font_small, buf, 92, 62, ARGB(230, 255, 210, 90));
  }
  for (int i = 0; i < 3; i++) {
    int lx = SCREEN_W - 60 - i * 54;
    if (i < lives) blit(spr_pumpkin1, lx - 4, 6);
    else blitA(spr_pumpkin0, lx - 4, 6, 60);
  }

  drawBackButton();
  if (backTapped()) { gScene = SC_MENU; return; }

  if (flashT > 0) {
    flashT -= dt;
    dimRect(0, 0, SCREEN_W, SCREEN_H, (uint8_t)(120 * (flashT / 0.4f)), rgb565(255, 30, 30));
  } else if (!over) {
    led(20, 40, 24);
  }

  if (gameT < 2.4f && !over) {
    uint8_t a = gameT < 1.6f ? 255 : (uint8_t)(255 * (2.4f - gameT) / 0.8f);
    textCenter(font_hud, "DRAG THE CAULDRON", SCREEN_W / 2, 150, ARGB(a, 240, 235, 255));
    textCenter(font_small, "CATCH TREATS   DODGE SKULLS", SCREEN_W / 2, 186, ARGB(a, 190, 255, 170));
  }

  if (over) {
    shakeX = 0; shakeY = 0;
    int r = gameOverTick("BREW RUINED", score, &hiCatch);
    if (r == 1) catchEnter();
    else if (r == 2) gScene = SC_MENU;
  }
}

void catchComposeBg() { composeCatchBg(); }

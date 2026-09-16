#include "scenes.h"

using namespace eng;

// Layout: a live graveyard diorama fills the left 400 px (everything animated
// is clipped to it), and a static panel on the right carries the title and the
// three game cards. The panel, title and cards are baked into bgMenu on entry,
// so a frame only costs the layer copy plus the diorama.

static const int DIO_W = 400;
static const int PX = 410, PW = 378, PH = 104;   // card geometry
static const int PY[3] = { 124, 242, 360 };

struct Card {
  const char* name; const Sprite* icon; int iy; uint16_t hot; int* best;
};
static Card cards[3] = {
  { "PUMPKIN WHACK",  &spr_ico_pumpkin,  13, rgb565(255, 150, 30),  &hiWhack },
  { "FLAPPY BAT",     &spr_ico_bat,      22, rgb565(150, 110, 255), &hiBat   },
  { "CAULDRON CATCH", &spr_ico_cauldron, 12, rgb565(90, 220, 90),   &hiCatch },
};

static void drawCard(int i, bool hot) {
  Card& c = cards[i];
  int y = PY[i];
  if (hot) {
    blitTint(spr_glow_l, PX + PW / 2 - 150, y + PH / 2 - 150, ARGB(70, 255, 220, 160));
    fillRoundRect(PX - 3, y - 3, PW + 6, PH + 6, 16, c.hot);
  } else {
    dimRect(PX + 5, y + 7, PW, PH, 120, rgb565(0, 0, 0));
    fillRoundRect(PX, y, PW, PH, 14, rgb565(46, 26, 66));
  }
  fillRoundRect(PX + 4, y + 4, PW - 8, PH - 8, 11, rgb565(22, 11, 34));
  dimRect(PX + 4, y + 4, 112, PH - 8, hot ? 120 : 64, c.hot);   // icon well
  blit(*c.icon, PX + 12, y + c.iy);

  text(font_hud, c.name, PX + 128, y + 46, ARGB(255, 250, 240, 255));
  char b[24];
  snprintf(b, sizeof(b), "BEST  %d", *c.best);
  text(font_small, b, PX + 128, y + 80, ARGB(225, 190, 170, 220));
  // play chevron
  for (int k = 0; k < 14; k++) {
    int hw = 14 - k;
    fillRect(PX + PW - 40 + k, y + PH / 2 - hw, 3, hw * 2, hot ? c.hot : rgb565(120, 90, 160));
  }
}

static void composeMenuBg() {
  layerTarget(bgMenu);
  layerVGrad(rgb565(10, 4, 26), rgb565(58, 22, 46), 0, 300);
  layerVGrad(rgb565(58, 22, 46), rgb565(120, 48, 30), 300, SCREEN_H);
  starsCompose(190, 0xBEEF01);

  // --- diorama (left) ---
  layerGlow(120, 110, 150, 90, 78, 40);
  blit(spr_moon, 20, 10);
  blitTint(spr_cloud0, -40, 66, ARGB(150, 120, 100, 150));
  blitTint(spr_cloud1, 120, 150, ARGB(120, 100, 84, 130));

  hillsCompose(rgb565(46, 22, 52), 322, 16, 620, 7, 190, 0);
  hillsCompose(rgb565(22, 10, 30), 372, 13, 430, 6, 150, 200);

  blitTint(spr_tree, 190, 96, ARGB(255, 12, 6, 18));
  blit(spr_grave0, 22, 300);
  blit(spr_grave1, 296, 292);
  blit(spr_grave2, 150, 316);

  fillRect(0, 404, SCREEN_W, SCREEN_H - 404, rgb565(16, 8, 22));
  for (int x = 0; x < SCREEN_W; x++) {
    int y = 404 + (int)(5 * sinf(x * 0.05f));
    vline(x, y, y + 3, rgb565(40, 22, 40));
  }
  for (int i = 0; i < 5; i++)
    dimRect(0, 396 + i * 9, SCREEN_W, 8, 26 + i * 6, rgb565(150, 140, 190));

  // --- right panel ---
  dimRect(DIO_W, 0, SCREEN_W - DIO_W, SCREEN_H, 215, rgb565(10, 5, 20));
  fillRect(DIO_W, 0, 3, SCREEN_H, rgb565(70, 40, 96));
  blitTint(spr_title, PX - 6, 6, ARGB(255, 255, 140, 25));
  blitTint(spr_title_sub, PX + 90, 78, ARGB(235, 180, 150, 230));
  for (int i = 0; i < 3; i++) drawCard(i, false);

  layerTarget(nullptr);
}

// ---------------------------------------------------------------- state

struct MenuBat { float x, y, vx, amp, ph, sp; };
static MenuBat mbats[5];
static float t, witchT, lightT, lightNext, fadeT, ghostPh;
static int fadeTo;

void menuEnter() {
  t = 0; witchT = -3; lightT = 0; lightNext = 5.5f; fadeT = 0; fadeTo = -1; ghostPh = 0;
  clearParticles();
  for (int i = 0; i < 5; i++)
    mbats[i] = { (float)rndi(-300, DIO_W), (float)rndi(40, 250), 50.0f + rndf() * 60,
                 10.0f + rndf() * 22, rndf() * 6.28f, 2.0f + rndf() * 3.0f };
  composeMenuBg();   // picks up new best scores
}

void menuTick() {
  t += dt;
  layerFrom(bgMenu);

  setClip(0, 0, DIO_W, SCREEN_H);   // the diorama never spills onto the panel

  // --- witch ---
  witchT += dt;
  if (witchT > 15.0f) witchT = -2.0f;
  if (witchT > 0 && witchT < 7.0f) {
    float p = witchT / 7.0f;
    int wx = (int)(-170 + p * (DIO_W + 340));
    int wy = (int)(150 - 66 * sinf(p * 3.14159f) + 14 * sinf(witchT * 3.0f));
    blitTint(((int)(witchT * 5) & 1) ? spr_witch1 : spr_witch0, wx, wy, ARGB(235, 10, 5, 14));
    if ((frameNo & 3) == 0)
      spawnParticle(P_SPARK, wx + 10, wy + 58, -20 - rndf() * 40, -10 + rndf() * 20,
                    0.8f, rgb565(140, 90, 220));
  }

  // --- bats ---
  for (auto& b : mbats) {
    b.x += b.vx * dt;
    if (b.x > DIO_W + 50) { b.x = -70; b.y = rndi(40, 250); }
    float y = b.y + sinf(t * b.sp + b.ph) * b.amp;
    int fr = ((int)(t * b.sp * 1.6f + b.ph) % 3 + 3) % 3;
    const Sprite* s = fr == 0 ? &spr_bat_s0 : (fr == 1 ? &spr_bat_s1 : &spr_bat_s2);
    blitTint(*s, (int)b.x, (int)y, ARGB(225, 26, 14, 40));
  }

  // --- ghost rising out of the graves ---
  ghostPh += dt;
  blit(((int)(ghostPh * 2) & 1) ? spr_ghost0 : spr_ghost1,
       210 + (int)(26 * sinf(ghostPh * 0.55f)), 232 + (int)(18 * sinf(ghostPh * 1.2f)));

  // --- flickering jack-o'-lanterns ---
  for (int i = 0; i < 2; i++) {
    int pxp = i ? 236 : 24, pyp = i ? 350 : 358;
    bool bright = (rnd() & 7) > 1;
    blitTint(spr_glow_s, pxp + 66 - 80, pyp + 60 - 80, ARGB(bright ? 150 : 110, 255, 140, 30));
    blit(bright ? spr_pumpkin1 : spr_pumpkin0, pxp, pyp);
    if ((frameNo % 7) == (uint32_t)i * 3)
      spawnParticle(P_EMBER, pxp + 50 + rndf() * 30, pyp + 18, -12 + rndf() * 24,
                    -40 - rndf() * 45, 1.4f + rndf(), rgb565(255, 170, 40), rndi(0, 200));
  }

  updateDrawParticles();
  clearClip();

  // --- hovered card ---
  int hotCard = -1, tapped = -1;
  if (touch.down && touch.x >= PX - 10) {
    for (int i = 0; i < 3; i++)
      if (touch.y >= PY[i] - 6 && touch.y < PY[i] + PH + 6) hotCard = i;
  }
  if (hotCard >= 0) {
    drawCard(hotCard, true);
    if (touch.pressed) tapped = hotCard;
  }

  // --- lightning ---
  lightT += dt;
  if (lightT > lightNext) {
    if (lightT < lightNext + 0.09f || (lightT > lightNext + 0.16f && lightT < lightNext + 0.24f)) {
      dimRect(0, 0, SCREEN_W, SCREEN_H, 150, rgb565(230, 225, 255));
      led(90, 90, 120);
    } else {
      led(10, 2, 16);
    }
    if (lightT > lightNext + 0.4f) { lightT = 0; lightNext = 6.0f + rndf() * 9.0f; }
  } else {
    led(14, 3, 20);
  }

  // --- transition ---
  if (tapped >= 0 && fadeTo < 0) fadeTo = tapped;
  if (fadeTo >= 0) {
    fadeT += dt * 4.0f;
    dimRect(0, 0, SCREEN_W, SCREEN_H, (uint8_t)(min(1.0f, fadeT) * 255), rgb565(0, 0, 0));
    if (fadeT >= 1.0f) {
      gScene = fadeTo == 0 ? SC_WHACK : (fadeTo == 1 ? SC_BAT : SC_CATCH);
      fadeTo = -1; fadeT = 0;
    }
  }
}

void menuComposeBg() { composeMenuBg(); }

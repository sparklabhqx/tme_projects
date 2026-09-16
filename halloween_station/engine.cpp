#include "engine.h"
#include "dsi.h"
#include "SDRAM.h"
#include "Arduino_GigaDisplayTouch.h"
#include "GigaDisplayRGB.h"

// Landscape (x,y) -> portrait (px,py) = (479 - y, x); fb index = px + 480*py.
// A landscape rect (x,y,w,h) is the portrait rect (480-y-h, x, h, w).

namespace eng {

TouchState touch;
float dt = 0.016f;
uint32_t frameNo = 0;
float fps = 0;
int shakeX = 0, shakeY = 0;
float msScene = 0, msPresent = 0;

static DMA2D_HandleTypeDef hd;
static uint16_t* layerOverride = nullptr;
static uint8_t* solidA8 = nullptr;   // FB-sized 0xFF plane for dimRect
static GigaDisplayRGB rgbLed;
static uint32_t lastLedMs = 0;
static uint8_t curR = 0, curG = 0, curB = 0;
static uint32_t rndState = 0x1234567;
static uint32_t lastFrameUs = 0;

static Arduino_GigaDisplayTouch touchCtl;

// injected (serial) touch
static bool injActive = false, injDown = false;
static int injX = 0, injY = 0;
static uint32_t injUntil = 0;
static bool prevDown = false;

static inline uint16_t* targetFB() {
  return layerOverride ? layerOverride : (uint16_t*)dsi_getCurrentFrameBuffer();
}

// clip rect in landscape screen space (shake is added at use time)
static int clX0 = 0, clY0 = 0, clX1 = SCREEN_W, clY1 = SCREEN_H;

void setClip(int x, int y, int w, int h) {
  clX0 = max(0, x); clY0 = max(0, y);
  clX1 = min(SCREEN_W, x + w); clY1 = min(SCREEN_H, y + h);
}
void clearClip() { clX0 = 0; clY0 = 0; clX1 = SCREEN_W; clY1 = SCREEN_H; }

// ------------------------------------------------------------------ DMA2D

static void dma2dWait() {
  HAL_DMA2D_PollForTransfer(&hd, 30);
}

// In R2M mode the HAL expects the colour as ARGB8888 and packs it down to the
// output format itself — handing it a raw RGB565 word silently mangles it.
static inline uint32_t to8888(uint16_t c) {
  uint32_t r = (c >> 11) & 0x1F, g = (c >> 5) & 0x3F, b = c & 0x1F;
  r = (r << 3) | (r >> 2); g = (g << 2) | (g >> 4); b = (b << 3) | (b >> 2);
  return (r << 16) | (g << 8) | b;
}

static void dma2dFill(uint16_t* dst, int wpx, int hln, int dstStride, uint16_t c) {
  hd.Instance = DMA2D;
  hd.Init.Mode = DMA2D_R2M;
  hd.Init.ColorMode = DMA2D_OUTPUT_RGB565;
  hd.Init.OutputOffset = dstStride - wpx;
  HAL_DMA2D_Init(&hd);
  HAL_DMA2D_Start(&hd, to8888(c), (uint32_t)dst, wpx, hln);
  dma2dWait();
}

static void dma2dCopy(const void* src, int srcStride, uint16_t* dst, int dstStride,
                      int wpx, int hln) {
  hd.Instance = DMA2D;
  hd.Init.Mode = DMA2D_M2M;
  hd.Init.ColorMode = DMA2D_OUTPUT_RGB565;
  hd.Init.OutputOffset = dstStride - wpx;
  HAL_DMA2D_Init(&hd);
  hd.LayerCfg[1].AlphaMode = DMA2D_NO_MODIF_ALPHA;
  hd.LayerCfg[1].InputAlpha = 0xFF;
  hd.LayerCfg[1].InputColorMode = DMA2D_INPUT_RGB565;
  hd.LayerCfg[1].InputOffset = srcStride - wpx;
  HAL_DMA2D_ConfigLayer(&hd, 1);
  HAL_DMA2D_Start(&hd, (uint32_t)src, (uint32_t)dst, wpx, hln);
  dma2dWait();
}

// blend src (fmt+stride) over dst in place
static void dma2dBlend(const void* src, uint32_t inFmt, uint32_t inAlpha, uint32_t alphaMode,
                       int srcStride, uint16_t* dst, int dstStride, int wpx, int hln) {
  hd.Instance = DMA2D;
  hd.Init.Mode = DMA2D_M2M_BLEND;
  hd.Init.ColorMode = DMA2D_OUTPUT_RGB565;
  hd.Init.OutputOffset = dstStride - wpx;
  HAL_DMA2D_Init(&hd);
  hd.LayerCfg[1].AlphaMode = alphaMode;
  hd.LayerCfg[1].InputAlpha = inAlpha;
  hd.LayerCfg[1].InputColorMode = inFmt;
  hd.LayerCfg[1].InputOffset = srcStride - wpx;
  HAL_DMA2D_ConfigLayer(&hd, 1);
  hd.LayerCfg[0].AlphaMode = DMA2D_NO_MODIF_ALPHA;
  hd.LayerCfg[0].InputAlpha = 0xFF;
  hd.LayerCfg[0].InputColorMode = DMA2D_INPUT_RGB565;
  hd.LayerCfg[0].InputOffset = dstStride - wpx;
  HAL_DMA2D_ConfigLayer(&hd, 0);
  HAL_DMA2D_BlendingStart(&hd, (uint32_t)src, (uint32_t)dst, (uint32_t)dst, wpx, hln);
  dma2dWait();
}

// ------------------------------------------------------------------ core draws

void clear(uint16_t c) {
  dma2dFill(targetFB(), FB_W, FB_H, FB_W, c);
}

void fillRect(int x, int y, int w, int h, uint16_t c) {
  x += shakeX; y += shakeY;
  int cx0 = clX0 + shakeX, cy0 = clY0 + shakeY, cx1 = clX1 + shakeX, cy1 = clY1 + shakeY;
  cx0 = max(cx0, 0); cy0 = max(cy0, 0);
  cx1 = min(cx1, SCREEN_W); cy1 = min(cy1, SCREEN_H);
  if (x < cx0) { w -= (cx0 - x); x = cx0; }
  if (y < cy0) { h -= (cy0 - y); y = cy0; }
  if (x + w > cx1) w = cx1 - x;
  if (y + h > cy1) h = cy1 - y;
  if (w <= 0 || h <= 0) return;
  uint16_t* dst = targetFB() + (FB_W - y - h) + FB_W * x;
  if (w * h < 160) {  // small: CPU vertical-run fill (portrait rows are landscape columns)
    for (int i = 0; i < w; i++) {
      uint16_t* p = dst + FB_W * i;
      for (int j = 0; j < h; j++) p[j] = c;
    }
    return;
  }
  dma2dFill(dst, h, w, FB_W, c);
}

void dimRect(int x, int y, int w, int h, uint8_t alpha, uint16_t c) {
  x += shakeX; y += shakeY;
  int cx0 = max(clX0 + shakeX, 0), cy0 = max(clY0 + shakeY, 0);
  int cx1 = min(clX1 + shakeX, SCREEN_W), cy1 = min(clY1 + shakeY, SCREEN_H);
  if (x < cx0) { w -= (cx0 - x); x = cx0; }
  if (y < cy0) { h -= (cy0 - y); y = cy0; }
  if (x + w > cx1) w = cx1 - x;
  if (y + h > cy1) h = cy1 - y;
  if (w <= 0 || h <= 0) return;
  uint16_t* dst = targetFB() + (FB_W - y - h) + FB_W * x;
  uint8_t r8 = ((c >> 11) & 0x1F) << 3, g8 = ((c >> 5) & 0x3F) << 2, b8 = (c & 0x1F) << 3;
  dma2dBlend(solidA8, DMA2D_INPUT_A8, ARGB(alpha, r8, g8, b8), DMA2D_COMBINE_ALPHA,
             h, dst, FB_W, h, w);
}

void vline(int x, int y0, int y1, uint16_t c) {
  x += shakeX; y0 += shakeY; y1 += shakeY;
  int cx0 = max(clX0 + shakeX, 0), cy0 = max(clY0 + shakeY, 0);
  int cx1 = min(clX1 + shakeX, SCREEN_W), cy1 = min(clY1 + shakeY, SCREEN_H);
  if (x < cx0 || x >= cx1) return;
  if (y0 < cy0) y0 = cy0;
  if (y1 > cy1 - 1) y1 = cy1 - 1;
  if (y1 < y0) return;
  uint16_t* p = targetFB() + (FB_W - 1 - y1) + FB_W * x;
  int n = y1 - y0 + 1;
  for (int i = 0; i < n; i++) p[i] = c;
}

void px(int x, int y, uint16_t c) {
  x += shakeX; y += shakeY;
  if ((unsigned)x >= SCREEN_W || (unsigned)y >= SCREEN_H) return;
  if (x < clX0 + shakeX || x >= clX1 + shakeX || y < clY0 + shakeY || y >= clY1 + shakeY) return;
  targetFB()[(FB_W - 1 - y) + FB_W * x] = c;
}

void fillCircle(int cx, int cy, int r, uint16_t c) {
  for (int dx = -r; dx <= r; dx++) {
    int hh = (int)sqrtf((float)(r * r - dx * dx));
    vline(cx + dx, cy - hh, cy + hh, c);
  }
}

void fillRoundRect(int x, int y, int w, int h, int r, uint16_t c) {
  fillRect(x + r, y, w - 2 * r, h, c);
  for (int dx = 0; dx < r; dx++) {
    int hh = (int)sqrtf((float)(r * r - (r - dx) * (r - dx)));
    vline(x + dx, y + r - hh, y + h - 1 - r + hh, c);
    vline(x + w - 1 - dx, y + r - hh, y + h - 1 - r + hh, c);
  }
}

static void blitCore(const Sprite& s, int x0, int y0, uint32_t tint, uint32_t alphaMode) {
  x0 += shakeX; y0 += shakeY;
  int cx0 = max(clX0 + shakeX, 0), cy0 = max(clY0 + shakeY, 0);
  int cx1 = min(clX1 + shakeX, SCREEN_W), cy1 = min(clY1 + shakeY, SCREEN_H);
  int lw = s.lw, lh = s.lh;
  int sx0 = x0 < cx0 ? cx0 - x0 : 0;
  int sy0 = y0 < cy0 ? cy0 - y0 : 0;
  int x0c = x0 < cx0 ? cx0 : x0;
  int y0c = y0 < cy0 ? cy0 : y0;
  int vw = lw - sx0; if (x0c + vw > cx1) vw = cx1 - x0c;
  int vh = lh - sy0; if (y0c + vh > cy1) vh = cy1 - y0c;
  if (vw <= 0 || vh <= 0) return;
  // portrait dest block: rows py0.., cols px0..; vh wide, vw tall
  int px0 = FB_W - (y0c + vh);
  int py0 = x0c;
  int pcs = lh - sy0 - vh;                 // starting portrait column inside sprite
  uint16_t* dst = targetFB() + px0 + FB_W * py0;
  if (s.fmt == FMT_A8) {
    const uint8_t* src = (const uint8_t*)s.data + sx0 * lh + pcs;
    dma2dBlend(src, DMA2D_INPUT_A8, tint, DMA2D_COMBINE_ALPHA, lh, dst, FB_W, vh, vw);
  } else if (s.fmt == FMT_ARGB4444) {
    const uint16_t* src = (const uint16_t*)s.data + sx0 * lh + pcs;
    dma2dBlend(src, DMA2D_INPUT_ARGB4444, tint, alphaMode, lh, dst, FB_W, vh, vw);
  } else {
    const uint16_t* src = (const uint16_t*)s.data + sx0 * lh + pcs;
    dma2dCopy(src, lh, dst, FB_W, vh, vw);
  }
}

void blit(const Sprite& s, int x, int y) {
  blitCore(s, x, y, 0xFF, DMA2D_NO_MODIF_ALPHA);
}

// non-A8 formats take a plain 0..255 alpha (the HAL shifts it into place)
void blitA(const Sprite& s, int x, int y, uint8_t alpha) {
  blitCore(s, x, y, alpha, DMA2D_COMBINE_ALPHA);
}

void blitTint(const Sprite& s, int x, int y, uint32_t argb) {
  blitCore(s, x, y, argb, DMA2D_COMBINE_ALPHA);
}

// ------------------------------------------------------------------ layers

uint16_t* allocLayer() {
  return (uint16_t*)SDRAM.malloc(FB_W * FB_H * 2);
}

void layerTarget(uint16_t* layer) { layerOverride = layer; }

void layerFrom(const uint16_t* layer) {
  if (shakeX == 0 && shakeY == 0) {
    dma2dCopy(layer, FB_W, targetFB(), FB_W, FB_W, FB_H);
    return;
  }
  // shaken: shifted copy, black borders
  int dx = shakeX, dy = shakeY;   // landscape shift -> portrait shift (-dy, dx)
  int pdx = -dy, pdy = dx;
  int w = FB_W - abs(pdx), h = FB_H - abs(pdy);
  const uint16_t* src = layer + (pdx < 0 ? -pdx : 0) + FB_W * (pdy < 0 ? -pdy : 0);
  uint16_t* dst = targetFB() + (pdx > 0 ? pdx : 0) + FB_W * (pdy > 0 ? pdy : 0);
  dma2dFill(targetFB(), FB_W, FB_H, FB_W, 0x0000);
  dma2dCopy(src, FB_W, dst, FB_W, w, h);
}

// landscape x maps to whole portrait rows, so an x-scroll is two row-range copies
void layerFromScroll(const uint16_t* layer, int offsetX) {
  int off = offsetX % FB_H;
  if (off < 0) off += FB_H;
  uint16_t* dst = targetFB();
  int first = FB_H - off;
  if (first > 0) dma2dCopy(layer + (size_t)off * FB_W, FB_W, dst, FB_W, FB_W, first);
  if (off > 0) dma2dCopy(layer, FB_W, dst + (size_t)first * FB_W, FB_W, FB_W, off);
}

void layerVGrad(uint16_t topColor, uint16_t botColor, int y0, int y1) {
  static uint16_t row[FB_W];
  int tr = (topColor >> 11) & 0x1F, tg = (topColor >> 5) & 0x3F, tb = topColor & 0x1F;
  int br = (botColor >> 11) & 0x1F, bg = (botColor >> 5) & 0x3F, bb = botColor & 0x1F;
  int pxa = FB_W - y1;        // portrait col range for landscape rows y0..y1-1
  int pxb = FB_W - y0;
  for (int p = pxa; p < pxb; p++) {
    int y = FB_W - 1 - p;     // landscape y
    float t = (float)(y - y0) / (float)(y1 - y0);
    int r = tr + (int)((br - tr) * t), g = tg + (int)((bg - tg) * t), b = tb + (int)((bb - tb) * t);
    row[p] = (r << 11) | (g << 5) | b;
  }
  uint16_t* dst = targetFB();
  for (int py = 0; py < FB_H; py++)
    memcpy(dst + py * FB_W + pxa, row + pxa, (pxb - pxa) * 2);
}

void layerGlow(int cx, int cy, int r, uint8_t rr, uint8_t gg, uint8_t bb) {
  uint16_t* dst = targetFB();
  int pcx = FB_W - 1 - cy, pcy = cx;
  int pxa = max(0, pcx - r), pxb = min(FB_W - 1, pcx + r);
  int pya = max(0, pcy - r), pyb = min(FB_H - 1, pcy + r);
  for (int py = pya; py <= pyb; py++) {
    int dy2 = (py - pcy) * (py - pcy);
    uint16_t* prow = dst + py * FB_W;
    for (int p = pxa; p <= pxb; p++) {
      int d2 = dy2 + (p - pcx) * (p - pcx);
      if (d2 >= r * r) continue;
      float t = 1.0f - sqrtf((float)d2) / (float)r;
      t = t * t;
      uint16_t c = prow[p];
      int cr = ((c >> 11) & 0x1F) + (int)(t * (rr >> 3));
      int cg = ((c >> 5) & 0x3F) + (int)(t * (gg >> 2));
      int cb = (c & 0x1F) + (int)(t * (bb >> 3));
      if (cr > 31) cr = 31; if (cg > 63) cg = 63; if (cb > 31) cb = 31;
      prow[p] = (cr << 11) | (cg << 5) | cb;
    }
  }
}

// ------------------------------------------------------------------ text

static const Glyph* glyphFor(const BFont& f, char ch) {
  if (ch >= 'a' && ch <= 'z') ch -= 32;
  if (ch < 32 || ch > 90) return nullptr;
  return &f.glyphs[ch - 32];
}

int textWidth(const BFont& f, const char* s) {
  int w = 0;
  for (; *s; s++) { const Glyph* g = glyphFor(f, *s); if (g) w += g->adv; }
  return w;
}

void text(const BFont& f, const char* s, int x, int y, uint32_t argb) {
  for (; *s; s++) {
    const Glyph* g = glyphFor(f, *s);
    if (!g) continue;
    if (g->data) {
      Sprite tmp = { g->pw, g->ph, g->ph, g->pw, FMT_A8, g->data };
      blitTint(tmp, x + g->ox, y + g->oy, argb);
    }
    x += g->adv;
  }
}

void textCenter(const BFont& f, const char* s, int cx, int y, uint32_t argb) {
  text(f, s, cx - textWidth(f, s) / 2, y, argb);
}

// ------------------------------------------------------------------ rng / led

uint32_t rnd() {
  rndState ^= rndState << 13; rndState ^= rndState >> 17; rndState ^= rndState << 5;
  return rndState;
}
int rndi(int lo, int hi) { return lo + (int)(rnd() % (uint32_t)(hi - lo + 1)); }
float rndf() { return (rnd() & 0xFFFFFF) / 16777216.0f; }

void led(uint8_t r, uint8_t g, uint8_t b) {
  uint32_t now = millis();
  if (now - lastLedMs < 30 && !(r == 0 && g == 0 && b == 0)) return;
  if (r == curR && g == curG && b == curB) return;
  curR = r; curG = g; curB = b; lastLedMs = now;
  rgbLed.on(r, g, b);
}

// ------------------------------------------------------------------ particles

static Particle pool[256];

void clearParticles() { for (auto& p : pool) p.type = P_NONE; }

void spawnParticle(PType t, float x, float y, float vx, float vy, float life,
                   uint16_t color, uint8_t aux) {
  for (auto& p : pool) {
    if (p.type == P_NONE) {
      p = { t, aux, x, y, vx, vy, life, life, color };
      return;
    }
  }
}

void updateDrawParticles() {
  const Sprite* chunks[3] = { &spr_chunk0, &spr_chunk1, &spr_chunk2 };
  for (auto& p : pool) {
    if (p.type == P_NONE) continue;
    p.life -= dt;
    if (p.life <= 0 || p.y > SCREEN_H + 30) { p.type = P_NONE; continue; }
    p.x += p.vx * dt; p.y += p.vy * dt;
    float lt = p.life / p.maxlife;
    switch (p.type) {
      case P_CHUNK:
        p.vy += 900.0f * dt;
        blit(*chunks[p.aux % 3], (int)p.x, (int)p.y);
        break;
      case P_SPARK:
        p.vy += 500.0f * dt;
        if (lt > 0.3f || (frameNo & 1)) {
          px((int)p.x, (int)p.y, p.color);
          px((int)p.x + 1, (int)p.y, p.color);
          px((int)p.x, (int)p.y + 1, p.color);
        }
        break;
      case P_EMBER: {
        p.x += sinf(p.life * 5.0f + p.aux) * 18.0f * dt;
        if (lt > 0.35f || (frameNo & 1)) {
          uint16_t c = lt > 0.5f ? p.color : rgb565(200, 60, 10);
          fillRect((int)p.x, (int)p.y, 2, 2, c);
        }
        break;
      }
      case P_DOT:
      default:
        if (lt > 0.3f || (frameNo & 1)) fillRect((int)p.x, (int)p.y, 3, 3, p.color);
        break;
    }
  }
}

// ------------------------------------------------------------------ input

static void applyTouchSample(bool down, int lx, int ly) {
  touch.pressed = down && !prevDown;
  touch.released = !down && prevDown;
  touch.down = down;
  if (down) { touch.x = lx; touch.y = ly; }
  prevDown = down;
}

static void pollInput() {
  if (injActive) {
    if (injDown && millis() > injUntil) injDown = false;
    if (!injDown && !prevDown) injActive = false;
    applyTouchSample(injDown, injX, injY);
    return;
  }
  GDTpoint_t pts[5];
  uint8_t n = touchCtl.getTouchPoints(pts);
  if (n > 0) {
    int lx = pts[0].y;                 // portrait -> landscape
    int ly = (FB_W - 1) - pts[0].x;
    if (lx < 0) lx = 0; if (lx > SCREEN_W - 1) lx = SCREEN_W - 1;
    if (ly < 0) ly = 0; if (ly > SCREEN_H - 1) ly = SCREEN_H - 1;
    applyTouchSample(true, lx, ly);
  } else {
    applyTouchSample(false, touch.x, touch.y);
  }
}

// ------------------------------------------------------------------ serial debug

static void dumpFramebuffer() {
  const uint8_t* fb = (const uint8_t*)dsi_getActiveFrameBuffer();
  Serial.print("FBSHOT 480 800\n");
  Serial.flush();
  const int CH = 8192;
  for (int off = 0; off < FB_W * FB_H * 2; off += CH) {
    int n = min(CH, FB_W * FB_H * 2 - off);
    Serial.write(fb + off, n);
  }
  Serial.flush();
  Serial.print("\nFBDONE\n");
}

static char lineBuf[32];
static int lineLen = 0;

static void handleLine(const char* ln) {
  switch (ln[0]) {
    case 'S': dumpFramebuffer(); break;
    case 'T': {
      int x, y;
      if (sscanf(ln + 1, "%d %d", &x, &y) == 2) {
        injActive = true; injDown = true; injX = x; injY = y;
        injUntil = millis() + 120;
      }
      break;
    }
    case 'H': {
      int x, y;
      if (sscanf(ln + 1, "%d %d", &x, &y) == 2) {
        injActive = true; injDown = true; injX = x; injY = y;
        injUntil = millis() + 60000;
      }
      break;
    }
    case 'U': injDown = false; injUntil = 0; break;
    case 'I':
      Serial.print("INFO fps="); Serial.print(fps, 1);
      Serial.print(" scene="); Serial.print(msScene, 1);
      Serial.print("ms present="); Serial.print(msPresent, 1);
      Serial.print("ms frame="); Serial.print(frameNo);
      Serial.print(" touch="); Serial.print(touch.down);
      Serial.print(" x="); Serial.print(touch.x);
      Serial.print(" y="); Serial.println(touch.y);
      break;
  }
}

static void handleSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen > 0) { lineBuf[lineLen] = 0; handleLine(lineBuf); lineLen = 0; }
    } else if (lineLen < (int)sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    }
  }
}

// ------------------------------------------------------------------ lifecycle

void begin() {
  __HAL_RCC_DMA2D_CLK_ENABLE();
  solidA8 = (uint8_t*)SDRAM.malloc(FB_W * FB_H);
  memset(solidA8, 0xFF, FB_W * FB_H);
  touchCtl.begin();
  rgbLed.begin();
  rndState = micros() | 1;
  lastFrameUs = micros();
}

void frameStart() {
  uint32_t now = micros();
  uint32_t d = now - lastFrameUs;
  lastFrameUs = now;
  dt = d / 1000000.0f;
  if (dt > 0.05f) dt = 0.05f;
  float inst = d > 0 ? 1000000.0f / d : 0;
  fps = fps * 0.95f + inst * 0.05f;
  frameNo++;
  handleSerial();
  pollInput();
}

void present() {
  dsi_drawCurrentFrameBuffer();
}

} // namespace eng

// Halloween Gaming Station — render/input engine for GIGA R1 + Display Shield.
// Landscape 800x480 logical coordinates on a portrait-native 480x800 panel:
// all assets are pre-rotated at generation time, fills/blits map rects
// landscape->portrait, so nothing rotates at runtime.
#pragma once
#include <Arduino.h>
#include "assets.h"

#define SCREEN_W 800
#define SCREEN_H 480
#define FB_W 480   // portrait framebuffer width (stride)
#define FB_H 800

static inline uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) {
  return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
}
#define ARGB(a, r, g, b) (((uint32_t)(a) << 24) | ((uint32_t)(r) << 16) | ((uint32_t)(g) << 8) | (uint32_t)(b))

namespace eng {

struct TouchState {
  bool down;      // finger on screen now
  bool pressed;   // went down this frame
  bool released;  // went up this frame
  int x, y;       // landscape coords
};

extern TouchState touch;
extern float dt;
extern uint32_t frameNo;
extern float fps;
extern int shakeX, shakeY;
extern float msScene, msPresent;   // profiling, reported by the serial 'I' command

void begin();
void frameStart();               // dt/fps + input poll + serial debug
void present();                  // swap buffers

// --- drawing, landscape coords (respect shakeX/shakeY) ---
void clear(uint16_t c);
void fillRect(int x, int y, int w, int h, uint16_t c);
void dimRect(int x, int y, int w, int h, uint8_t alpha, uint16_t c); // blended overlay
void fillCircle(int cx, int cy, int r, uint16_t c);
void fillRoundRect(int x, int y, int w, int h, int r, uint16_t c);
void vline(int x, int y0, int y1, uint16_t c);
void px(int x, int y, uint16_t c);
void blit(const Sprite& s, int x, int y);                    // ARGB4444/RGB565
void blitA(const Sprite& s, int x, int y, uint8_t alpha);    // ARGB4444 w/ global alpha
void blitTint(const Sprite& s, int x, int y, uint32_t argb); // A8 sprites
void setClip(int x, int y, int w, int h);
void clearClip();
// --- background layers in SDRAM ---
uint16_t* allocLayer();
void layerFrom(const uint16_t* layer);                       // full-screen copy -> back fb
void layerFromScroll(const uint16_t* layer, int offsetX);    // horizontally wrapped copy
void layerTarget(uint16_t* layer);                           // redirect draws into layer (nullptr = back fb)
void layerVGrad(uint16_t topColor, uint16_t botColor, int y0 = 0, int y1 = SCREEN_H);
void layerGlow(int cx, int cy, int r, uint8_t rr, uint8_t gg, uint8_t bb); // additive radial

// --- text (y = baseline) ---
int textWidth(const BFont& f, const char* s);
void text(const BFont& f, const char* s, int x, int y, uint32_t argb);
void textCenter(const BFont& f, const char* s, int cx, int y, uint32_t argb);

// --- misc ---
uint32_t rnd();
int rndi(int lo, int hi);        // inclusive
float rndf();                    // [0,1)
void led(uint8_t r, uint8_t g, uint8_t b);

// --- particles ---
enum PType : uint8_t { P_NONE = 0, P_DOT, P_EMBER, P_CHUNK, P_SPARK };
struct Particle {
  PType type; uint8_t aux;
  float x, y, vx, vy, life, maxlife;
  uint16_t color;
};
void spawnParticle(PType t, float x, float y, float vx, float vy, float life, uint16_t color, uint8_t aux = 0);
void updateDrawParticles();
void clearParticles();

} // namespace eng

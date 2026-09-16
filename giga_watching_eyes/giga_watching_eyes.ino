/*
 * WATCHING EYES
 *
 * Arduino GIGA R1 WiFi + GIGA Display Shield + OV7675 DVP camera.
 * Uses the same 800x480 landscape-on-portrait framebuffer setup as the
 * Halloween Arcade project. Everything runs locally on the GIGA:
 *
 *   camera -> TensorFlow Lite person classifier -> motion centroid -> eyes
 *
 * The person classifier gates the tracker, so ordinary scene motion does not
 * normally attract the gaze. Three overlapping classifier views provide a
 * coarse location even after a person stops moving.
 *
 * Serial @115200:
 *   I            print status
 *   S            dump active RGB565 display framebuffer (480x800 native)
 *   C            dump the latest 320x240 grayscale camera frame
 *   G x y        manual gaze, x/y in -100..100 (G 999 999 returns to camera)
 */

#include <Arduino.h>
#include <Arduino_H7_Video.h>
#include <Chirale_TensorFlowLite.h>
#include <GigaDisplayRGB.h>
#include <SDRAM.h>
#include <camera.h>
#include <dsi.h>
#include <ov767x.h>

#include "person_detect_model_data.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/system_setup.h"
#include "tensorflow/lite/schema/schema_generated.h"

// --------------------------------------------------------------------------
// Hardware and tuning

static constexpr int SCREEN_W = 800;
static constexpr int SCREEN_H = 480;
static constexpr int FB_W = 480;   // panel-native framebuffer stride
static constexpr int FB_H = 800;
static constexpr int CAM_W = 320;
static constexpr int CAM_H = 240;
static constexpr int MODEL_W = 96;
static constexpr int MODEL_H = 96;

// The front-facing mirror makes camera X agree with the apparent direction on
// the display. Change these only if the camera is mounted in another rotation.
static constexpr bool CAMERA_MIRROR_X = true;
static constexpr bool CAMERA_FLIP_Y = false;

static constexpr uint32_t CAPTURE_PERIOD_MS = 160;    // ~6 vision fps; display stays fluid
static constexpr uint32_t INFERENCE_PERIOD_MS = 560; // TFLM runs independently
static constexpr uint32_t PERSON_HOLD_MS = 3200;
static constexpr float PERSON_STRONG_THRESHOLD = 0.78f;
static constexpr float PERSON_MOVING_THRESHOLD = 0.62f;

Arduino_H7_Video Display(480, 800, GigaDisplayShield);
GigaDisplayRGB statusLed;
OV7675 imageSensor;
Camera camera(imageSensor);
FrameBuffer cameraFrame;

// --------------------------------------------------------------------------
// TensorFlow Lite Micro

static const tflite::Model* model = nullptr;
static tflite::MicroInterpreter* interpreter = nullptr;
static TfLiteTensor* modelInput = nullptr;
static TfLiteTensor* modelOutput = nullptr;
static constexpr int TENSOR_ARENA_BYTES = 160 * 1024;
alignas(16) static uint8_t tensorArena[TENSOR_ARENA_BYTES];

static bool cameraReady = false;
static bool mlReady = false;
static bool displayReady = false;

// --------------------------------------------------------------------------
// Tracking state

enum InferenceView : uint8_t { VIEW_FULL = 0, VIEW_LEFT = 1, VIEW_RIGHT = 2 };
static const InferenceView inferenceSequence[4] = {
  VIEW_FULL, VIEW_LEFT, VIEW_FULL, VIEW_RIGHT
};
static uint8_t inferenceStep = 0;
static float viewPerson[3] = {0.0f, 0.0f, 0.0f};
static float viewNoPerson[3] = {1.0f, 1.0f, 1.0f};
static uint32_t viewUpdatedMs[3] = {0, 0, 0};
static float personConfidence = 0.0f;
static uint8_t strongPersonStreak = 0;
static uint32_t lastPersonSeenMs = 0;
static bool humanPresent = false;

static uint8_t previousGrid[40 * 30];
static bool havePreviousGrid = false;
static float motionX = CAM_W * 0.5f;
static float motionY = CAM_H * 0.44f;
static float motionStrength = 0.0f;
static uint32_t lastUsefulMotionMs = 0;
static uint8_t cameraAverage = 90;

static float gazeX = 0.0f;
static float gazeY = 0.0f;
static float targetGazeX = 0.0f;
static float targetGazeY = 0.0f;
static bool manualGaze = false;
static float manualX = 0.0f;
static float manualY = 0.0f;

static uint32_t lastCaptureMs = 0;
static uint32_t lastInferenceMs = 0;
static uint32_t lastStatusMs = 0;
static uint32_t lastLoopUs = 0;
static float renderFps = 0.0f;
static uint32_t lastInferenceTimeMs = 0;

// --------------------------------------------------------------------------
// Rendering storage and helpers

static uint16_t* backdrop = nullptr;
static uint16_t* openEyesBase = nullptr; // black + fully open sclera/veins/tear ducts
static uint16_t* irisTexture[2] = {nullptr, nullptr};
static constexpr int IRIS_R = 68;
static constexpr int IRIS_D = IRIS_R * 2 + 1;
static constexpr int FRAME_BYTES = FB_W * FB_H * sizeof(uint16_t);
static DMA2D_HandleTypeDef dma2d;

struct EyeGeometry {
  int cx;
  int cy;
  int rx;
  int topRadius;
  int bottomRadius;
  bool leftEye;
};

static const EyeGeometry eyes[2] = {
  // Deliberately not a mirrored pair. Full opening is reserved for acquisition.
  {205, 242, 155, 78, 60, true},
  {595, 239, 155, 74, 58, false}
};

static constexpr int EYE_COLUMNS = 311;
struct EyeContour {
  int16_t top[EYE_COLUMNS];
  int16_t bottom[EYE_COLUMNS];
  int16_t seam[EYE_COLUMNS];
};
static EyeContour contours[2];
static int16_t irisHalfHeight[IRIS_D];

struct EyeAnimation {
  float opening[2] = {0.74f, 0.70f};
  float pupilRadius = 29.0f;
  float microX = 0.0f;
  float microY = 0.0f;
  float acquisition = 0.0f;
};
static EyeAnimation animation;


static inline int clampi(int v, int lo, int hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

static inline float clampf(float v, float lo, float hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

static inline uint16_t rgb565(int r, int g, int b) {
  r = clampi(r, 0, 255);
  g = clampi(g, 0, 255);
  b = clampi(b, 0, 255);
  return (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
}

static inline uint32_t noiseHash(uint32_t x) {
  x ^= x >> 16;
  x *= 0x7feb352dU;
  x ^= x >> 15;
  x *= 0x846ca68bU;
  return x ^ (x >> 16);
}

// Landscape (x,y) -> portrait-native framebuffer address.
static inline uint16_t* landscapePixel(uint16_t* fb, int x, int y) {
  return fb + (FB_W - 1 - y) + FB_W * x;
}

static inline void putPixel(uint16_t* fb, int x, int y, uint16_t color) {
  if ((unsigned)x < SCREEN_W && (unsigned)y < SCREEN_H) {
    *landscapePixel(fb, x, y) = color;
  }
}

static uint16_t blend565(uint16_t dst, int r, int g, int b, int alpha) {
  int dr = ((dst >> 11) & 31) * 255 / 31;
  int dg = ((dst >> 5) & 63) * 255 / 63;
  int db = (dst & 31) * 255 / 31;
  int ia = 255 - alpha;
  return rgb565((dr * ia + r * alpha) / 255,
                (dg * ia + g * alpha) / 255,
                (db * ia + b * alpha) / 255);
}

static void cleanDisplayCache(const void* data, size_t bytes) {
  // SDRAM allocations are only 4-byte aligned; M7 cache lines are 32 bytes.
  // Clean (not invalidate) partial boundary lines to preserve adjacent data.
  uintptr_t start = (uintptr_t)data & ~(uintptr_t)31U;
  uintptr_t end = ((uintptr_t)data + bytes + 31U) & ~(uintptr_t)31U;
  SCB_CleanDCache_by_Addr((uint32_t*)start, (int32_t)(end - start));
}

static void copyBackdropToBackBuffer() {
  uint16_t* dst = (uint16_t*)dsi_getCurrentFrameBuffer();
  const uint16_t* source = openEyesBase ? openEyesBase : backdrop;
  if (!source) {
    memset(dst, 0, FB_W * FB_H * sizeof(uint16_t));
    return;
  }

  // Both native framebuffers are cache-line aligned. Discard the CPU's old
  // view BEFORE DMA owns the back buffer, so stale lines cannot overwrite it.
  // The previous frame's dirty pixels were already cleaned before presenting.
  SCB_InvalidateDCache_by_Addr((uint32_t*)dst, FRAME_BYTES);
  dma2d.Instance = DMA2D;
  dma2d.Init.Mode = DMA2D_M2M;
  dma2d.Init.ColorMode = DMA2D_OUTPUT_RGB565;
  dma2d.Init.OutputOffset = 0;
  HAL_DMA2D_Init(&dma2d);
  dma2d.LayerCfg[1].AlphaMode = DMA2D_NO_MODIF_ALPHA;
  dma2d.LayerCfg[1].InputAlpha = 0xFF;
  dma2d.LayerCfg[1].InputColorMode = DMA2D_INPUT_RGB565;
  dma2d.LayerCfg[1].InputOffset = 0;
  HAL_DMA2D_ConfigLayer(&dma2d, 1);
  HAL_DMA2D_Start(&dma2d, (uint32_t)source, (uint32_t)dst, FB_W, FB_H);
  HAL_DMA2D_PollForTransfer(&dma2d, 30);
  // The CPU blends lids/highlights into DMA-written pixels. Invalidate again
  // after completion to discard any speculative cache fills during transfer.
  SCB_InvalidateDCache_by_Addr((uint32_t*)dst, FRAME_BYTES);
}

static void buildBackdrop() {
  // Absolutely no face, halo, UI, or almost-black vignette.
  if (backdrop) {
    memset(backdrop, 0, FRAME_BYTES);
    cleanDisplayCache(backdrop, FRAME_BYTES);
  }
}

static void buildEyeContours() {
  // Boot-only curves: asymmetric arches, a low inner canthus, small lid folds.
  // Animation uses these cached columns, never powf() per frame/pixel.
  for (int e = 0; e < 2; ++e) {
    const EyeGeometry& eye = eyes[e];
    EyeContour& c = contours[e];
    for (int i = 0; i < EYE_COLUMNS; ++i) {
      float q = (i - eye.rx) / (float)eye.rx;
      if (!eye.leftEye) q = -q; // positive points toward the tear duct
      float envelope = max(0.0f, 1.0f - q * q);
      float seam = eye.cy + 7.0f * q + 3.0f * q * q;
      float fold = sinf(q * 8.0f + e * 0.8f) * 1.4f + sinf(q * 17.0f) * 0.6f;
      c.seam[i] = (int16_t)seam;
      c.top[i] = (int16_t)(seam - eye.topRadius * powf(envelope, 0.65f) *
                          (1.0f - 0.19f * q) + fold * envelope);
      c.bottom[i] = (int16_t)(seam + eye.bottomRadius * powf(envelope, 0.83f) *
                             (1.0f + 0.13f * q) + fold * envelope * 0.6f);
    }
  }
}

static float irisNoise(float angle, int sectors, uint32_t seed) {
  // Periodic, interpolated angular noise gives distinct radial fiber bundles,
  // not the regular pinwheel produced by a single sine wave.
  float p = (angle + PI) * (sectors / (2.0f * PI));
  int i = (int)floorf(p);
  float t = p - i;
  t = t * t * (3.0f - 2.0f * t);
  int a = (i % sectors + sectors) % sectors;
  int b = (a + 1) % sectors;
  float n0 = (noiseHash(a + seed) & 1023) / 1023.0f;
  float n1 = (noiseHash(b + seed) & 1023) / 1023.0f;
  return n0 + (n1 - n0) * t;
}

static void buildIrisTextures() {
  for (int x = -IRIS_R; x <= IRIS_R; ++x) {
    irisHalfHeight[x + IRIS_R] = (int16_t)sqrtf((float)(IRIS_R * IRIS_R - x * x));
  }
  for (int e = 0; e < 2; ++e) {
    irisTexture[e] = (uint16_t*)SDRAM.malloc(IRIS_D * IRIS_D * sizeof(uint16_t));
    if (!irisTexture[e]) continue;
    for (int x = -IRIS_R; x <= IRIS_R; ++x) {
      for (int y = -IRIS_R; y <= IRIS_R; ++y) {
        float rr = sqrtf((float)(x * x + y * y)) / IRIS_R;
        uint16_t color = 0;
        if (rr <= 1.0f) {
          float a = atan2f((float)y, (float)x);
          uint32_t seed = 9137U + e * 7919U;
          float bundle = irisNoise(a + 0.022f * sinf(rr * 16.0f + a * 9.0f), 173, seed);
          float fine = irisNoise(a + rr * 0.009f, 367, seed + 311);
          float crypt = irisNoise(a, 61, seed + 701);
          float collarette = 0.53f + 0.045f * sinf(a * 19.0f) + 0.025f * (crypt - 0.5f);
          float gold = clampf((0.84f - rr) * 2.3f, 0.0f, 1.0f);
          float fibers = (bundle - 0.5f) * 66 + (fine - 0.5f) * 31;
          float rings = sinf(rr * 103.0f + bundle * 5.0f) * 3.0f;
          float lace = max(0.0f, 1.0f - fabsf(rr - collarette) / 0.07f);
          float pits = lace * max(0.0f, 0.55f - crypt) * 135.0f;
          float edge = 1.0f - clampf((rr - 0.86f) / 0.14f, 0.0f, 1.0f) * 0.87f;
          float r = 85 + gold * 76 + fibers + rings + lace * 22 - pits;
          float g = 91 + gold * 31 + fibers * 0.74f + rings - pits * 0.8f;
          float b = 40 + gold * 5 + fibers * 0.27f - pits * 0.3f;
          // Small irregular freckles interrupt the fibers; no emissive glow.
          uint32_t h = noiseHash((x + 80) * 1709U + (y + 80) * 313U + seed);
          if ((h & 255) < 7 && rr > 0.48f) { r *= 0.68f; g *= 0.66f; }
          color = rgb565((int)(r * edge), (int)(g * edge), (int)(b * edge));
        }
        // Pre-rotate each column exactly like the native framebuffer. Moving
        // irises are now clipped contiguous memcpy spans, not strided pixels.
        irisTexture[e][(x + IRIS_R) * IRIS_D + IRIS_R - y] = color;
      }
    }
  }
}

static bool insideEye(int eyeIndex, int x, int y) {
  int i = x - (eyes[eyeIndex].cx - eyes[eyeIndex].rx);
  const EyeContour& c = contours[eyeIndex];
  return i > 0 && i < EYE_COLUMNS - 1 && y >= c.top[i] && y <= c.bottom[i];
}

static void drawVein(uint16_t* fb, int eyeIndex,
                     int x0, int y0, int x1, int y1, int alpha) {
  int dx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
  int dy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
  int err = dx + dy;
  for (;;) {
    if (insideEye(eyeIndex, x0, y0)) {
      uint16_t* p = landscapePixel(fb, x0, y0);
      *p = blend565(*p, 126, 35, 49, alpha);
    }
    // Soft capillary halo, generated only once in SDRAM.
    if (insideEye(eyeIndex, x0, y0 + 1)) {
      uint16_t* p = landscapePixel(fb, x0, y0 + 1);
      *p = blend565(*p, 143, 58, 69, alpha / 4);
    }
    if (x0 == x1 && y0 == y1) break;
    int e2 = err * 2;
    if (e2 >= dy) { err += dy; x0 += sx; }
    if (e2 <= dx) { err += dx; y0 += sy; }
  }
}

static void renderStaticEye(uint16_t* fb, const EyeGeometry& eye, int eyeIndex) {
  const EyeContour& c = contours[eyeIndex];
  for (int i = 1; i < EYE_COLUMNS - 1; ++i) {
    int x = eye.cx - eye.rx + i;
    float corner = fabsf((i - eye.rx) / (float)eye.rx);
    for (int y = c.top[i]; y <= c.bottom[i]; ++y) {
      float yn = (y - c.top[i]) / (float)max(1, c.bottom[i] - c.top[i]);
      float rim = fabsf(yn - 0.54f) * 1.85f;
      float blood = corner * corner * corner;
      float mottling = sinf(x * 0.12f + sinf(y * 0.13f)) * sinf(y * 0.09f) * 3.5f;
      int grain = (int)(noiseHash(x * 92821U + y * 68917U) & 3) - 1;
      float upperShadow = max(0.0f, 0.40f - yn) * 85.0f;
      int r = (int)(225 - rim * 49 - blood * 22 - upperShadow + mottling) + grain;
      int g = (int)(218 - rim * 60 - blood * 66 - upperShadow + mottling) + grain;
      int b = (int)(194 - rim * 42 - blood * 39 - upperShadow * 0.72f + mottling);
      putPixel(fb, x, y, rgb565(r, g, b));
    }
  }

  // Tortuous, tapering vessels arriving from both canthi and the lid edges.
  for (int side = -1; side <= 1; side += 2) {
    for (int v = 0; v < 9; ++v) {
      uint32_t h = noiseHash((eyeIndex + 1) * 9001U + (side + 2) * 701U + v * 197U);
      int x0 = eye.cx + side * (eye.rx - 12 - (v % 3) * 16);
      int ci = x0 - (eye.cx - eye.rx);
      int y0 = c.top[ci] + (c.bottom[ci] - c.top[ci]) * (v + 1) / 11;
      int travel = 36 + (int)((h >> 8) % 52);
      int drift = (int)((h >> 16) % 59) - 29;
      float phase = (h & 255) / 255.0f * 2.0f * PI;
      int px = x0, py = y0;
      for (int s = 1; s <= 24; ++s) {
        float t = s / 24.0f;
        int nx = x0 - side * (int)(travel * t);
        int ny = y0 + (int)(drift * t + 3.2f * (sinf(t * 6.0f + phase) - sinf(phase)) +
                            1.3f * sinf(t * 13.0f));
        if (nx != px || ny != py) drawVein(fb, eyeIndex, px, py, nx, ny, 66 - s * 2);
        if (s == 10 || s == 17) {
          int branch = (h & (1U << s)) ? 1 : -1;
          int bx = nx, by = ny;
          for (int k = 1; k <= 7; ++k) {
            int ex = nx - side * k * 3;
            int ey = ny + branch * (int)(k * 1.5f + sinf(k * 0.6f) * 2);
            drawVein(fb, eyeIndex, bx, by, ex, ey, 34 - k * 3);
            bx = ex; by = ey;
          }
        }
        px = nx; py = ny;
      }
    }
  }

  int innerSign = eye.leftEye ? 1 : -1;
  int tearX = eye.cx + innerSign * (eye.rx - 15);
  for (int yy = -9; yy <= 9; ++yy) {
    for (int xx = -16; xx <= 16; ++xx) {
      float d = (xx * xx) / 256.0f + (yy * yy) / 81.0f;
      int px = tearX + xx, py = eye.cy + 8 + yy;
      if (d <= 1.0f && insideEye(eyeIndex, px, py)) {
        uint16_t* p = landscapePixel(fb, px, py);
        *p = blend565(*p, 122, 48, 59, (int)(190 * (1.0f - d)));
        float glint = (xx + 3) * (xx + 3) / 12.0f + (yy + 3) * (yy + 3) / 3.0f;
        if (glint < 1) *p = blend565(*p, 210, 177, 167, (int)((1 - glint) * 90));
      }
    }
  }
}

static void shadeLidMargins(uint16_t* fb, int x, int top, int bottom) {
  // All shadows and wet margins are INSIDE the aperture. Even a closed blink
  // leaves no skin-colored stroke, lashes, halo, or line across the darkness.
  if (bottom < top) return;
  static const uint8_t upperAlpha[] = {255, 244, 221, 186, 146, 105, 69, 39, 18};
  static const uint8_t lowerAlpha[] = {255, 235, 190, 122, 66, 25};
  for (int d = 0; d < 9 && top + d <= bottom; ++d) {
    uint16_t* p = landscapePixel(fb, x, top + d);
    *p = d == 0 ? 0 : blend565(*p, 13, 6, 14, upperAlpha[d]);
  }
  for (int d = 0; d < 6 && bottom - d > top; ++d) {
    uint16_t* p = landscapePixel(fb, x, bottom - d);
    *p = d == 0 ? 0 : blend565(*p, 30, 10, 22, lowerAlpha[d]);
  }
  // Broken, subdued tear-film glints; never a bright outlined almond.
  if (bottom - top > 22 && (noiseHash(x / 7) & 7) < 3) {
    uint16_t* p = landscapePixel(fb, x, bottom - 3);
    *p = blend565(*p, 135, 112, 103, 50);
  }
}

static void buildOpenEyesBase() {
  buildEyeContours();
  if (!openEyesBase) return;
  memset(openEyesBase, 0, FB_W * FB_H * sizeof(uint16_t));
  for (int e = 0; e < 2; ++e) {
    renderStaticEye(openEyesBase, eyes[e], e);
    for (int i = 1; i < EYE_COLUMNS - 1; ++i) {
      shadeLidMargins(openEyesBase, eyes[e].cx - eyes[e].rx + i,
                      contours[e].top[i], contours[e].bottom[i]);
    }
  }
  // Publish the immutable cached base once; DMA2D cannot read CPU cache lines.
  cleanDisplayCache(openEyesBase, FRAME_BYTES);
}

static void renderEye(uint16_t* fb, const EyeGeometry& eye, int eyeIndex,
                      float openness, float lookX, float lookY) {
  int irisCx = eye.cx + (int)(clampf(lookX, -1.0f, 1.0f) * 44.0f);
  int irisCy = eye.cy + (int)(clampf(lookY, -1.0f, 1.0f) * 27.0f);
  int16_t topAt[EYE_COLUMNS];
  int16_t bottomAt[EYE_COLUMNS];
  int eyeX0 = eye.cx - eye.rx;
  const EyeContour& c = contours[eyeIndex];
  openness = clampf(openness, 0.0f, 1.0f);
  for (int i = 0; i < EYE_COLUMNS; ++i) {
    // The upper lid does most of the closing; the lower lid rises less.
    int seam = c.seam[i] + 9;
    int top = c.top[i] + (int)((seam - c.top[i]) * (1.0f - openness));
    int bottom = c.bottom[i] - (int)((c.bottom[i] - seam) * (1.0f - openness));
    top = clampi(top, c.top[i], c.bottom[i]);
    bottom = clampi(bottom, c.top[i], c.bottom[i]);
    int x = eyeX0 + i;
    if (bottom - top < 3 || openness < 0.025f || i == 0 || i == EYE_COLUMNS - 1) {
      memset(landscapePixel(fb, x, c.bottom[i]), 0,
             (c.bottom[i] - c.top[i] + 1) * sizeof(uint16_t));
      topAt[i] = 1; bottomAt[i] = 0; // empty aperture
      continue;
    }
    topAt[i] = top; bottomAt[i] = bottom;
    if (top > c.top[i]) {
      memset(landscapePixel(fb, x, top - 1), 0, (top - c.top[i]) * sizeof(uint16_t));
    }
    if (bottom < c.bottom[i]) {
      memset(landscapePixel(fb, x, c.bottom[i]), 0,
             (c.bottom[i] - bottom) * sizeof(uint16_t));
    }
  }
  auto visible = [&](int x, int y) {
    int i = x - eyeX0;
    return (unsigned)i < EYE_COLUMNS && y >= topAt[i] && y <= bottomAt[i];
  };

  if (irisTexture[eyeIndex]) {
    for (int ix = -IRIS_R; ix <= IRIS_R; ++ix) {
      int px = irisCx + ix, i = px - eyeX0;
      if ((unsigned)i >= EYE_COLUMNS) continue;
      int half = irisHalfHeight[ix + IRIS_R];
      int top = max((int)topAt[i], irisCy - half);
      int bottom = min((int)bottomAt[i], irisCy + half);
      if (bottom < top) continue;
      const uint16_t* src = irisTexture[eyeIndex] + (ix + IRIS_R) * IRIS_D +
                            IRIS_R - (bottom - irisCy);
      memcpy(landscapePixel(fb, px, bottom), src, (bottom - top + 1) * sizeof(uint16_t));
    }
  }

  int pupilR = clampi((int)animation.pupilRadius, 22, 43);
  for (int x = -pupilR; x <= pupilR; ++x) {
    int px = irisCx + x, i = px - eyeX0;
    if ((unsigned)i >= EYE_COLUMNS) continue;
    float span = sqrtf((float)(pupilR * pupilR - x * x));
    int half = (int)span;
    int top = max((int)topAt[i], irisCy - half);
    int bottom = min((int)bottomAt[i], irisCy + half);
    if (bottom >= top) {
      memset(landscapePixel(fb, px, bottom), 0, (bottom - top + 1) * sizeof(uint16_t));
    }
    for (int side = -1; side <= 1; side += 2) {
      int y = irisCy + side * (half + 1);
      if (visible(px, y)) {
        uint16_t* p = landscapePixel(fb, px, y);
        *p = blend565(*p, 0, 0, 0, 75 + (int)((span - half) * 170));
      }
    }
  }

  // Soft, irregular rectangular light-source reflection on the corneal dome.
  // It crosses both pupil and iris instead of looking painted on the texture.
  int hx = irisCx - 19, hy = irisCy - 23;
  for (int y = -8; y <= 8; ++y) {
    for (int x = -12; x <= 12; ++x) {
      float nx = (x + y * 0.18f) / 12.0f, ny = y / 8.0f;
      float d = nx * nx * nx * nx + ny * ny * ny * ny;
      if (d < 1.0f && visible(hx + x, hy + y)) {
        uint16_t* p = landscapePixel(fb, hx + x, hy + y);
        int alpha = (int)(215 * clampf((1.0f - d) * 3.0f, 0.0f, 1.0f));
        if (x > 3 && x < 6) alpha = alpha * 3 / 5;
        *p = blend565(*p, 227, 238, 232, alpha);
      }
    }
  }
  for (int y = -2; y <= 2; ++y) {
    for (int x = -3; x <= 3; ++x) {
      if (x * x + y * y < 10 && visible(irisCx + 27 + x, irisCy + 21 + y)) {
        uint16_t* p = landscapePixel(fb, irisCx + 27 + x, irisCy + 21 + y);
        *p = blend565(*p, 189, 209, 194, 145);
      }
    }
  }
  // Faint curved reflection at the bottom of the cornea.
  for (int x = -29; x <= 22; ++x) {
    int y = irisCy + 45 - x * x / 85;
    if (visible(irisCx + x, y)) {
      uint16_t* p = landscapePixel(fb, irisCx + x, y);
      *p = blend565(*p, 147, 159, 128, 23);
    }
  }
  for (int i = 1; i < EYE_COLUMNS - 1; ++i) {
    shadeLidMargins(fb, eyeX0 + i, topAt[i], bottomAt[i]);
  }
}

static float smoothUnit(float t) {
  t = clampf(t, 0.0f, 1.0f);
  return t * t * (3.0f - 2.0f * t);
}

static void updateEyeAnimation(uint32_t now, float dt) {
  static bool wasHuman = false;
  static uint32_t acquiredMs = 0;
  static uint32_t nextMicroMs = 0;
  static float microTargetX = 0.0f, microTargetY = 0.0f;
  if (humanPresent && !wasHuman) acquiredMs = now;
  wasHuman = humanPresent;
  float age = (now - acquiredMs) / 1000.0f;
  animation.acquisition = humanPresent && age < 2.4f ?
                          smoothUnit(age / 0.13f) * (1.0f - smoothUnit(age / 2.4f)) : 0.0f;

  // Long, uneasy rests interspersed with a slow suspicious narrowing. Small
  // asymmetry is biological, not a wink; tracking never depends on animation.
  float breath = sinf(now * 0.00053f);
  float suspicion = max(0.0f, sinf(now * 0.00019f - 1.0f));
  suspicion *= suspicion;
  suspicion *= suspicion;
  suspicion *= suspicion;
  float desired = humanPresent ? 0.88f + animation.acquisition * 0.12f :
                                 0.75f + breath * 0.025f - suspicion * 0.30f;
  if (manualGaze) desired = 1.0f; // full aperture for repeatable clipping tests
  float follow = 1.0f - expf(-dt * (animation.acquisition > 0.1f ? 20.0f : 3.8f));
  for (int e = 0; e < 2; ++e) {
    float target = desired - (manualGaze ? 0.0f : e * (0.025f + suspicion * 0.03f));
    animation.opening[e] += (target - animation.opening[e]) * follow;
  }
  float pupil = 32.0f - cameraAverage / 255.0f * 8.0f +
                (humanPresent ? 2.0f : 0.0f) + animation.acquisition * 10.0f +
                sinf(now * 0.0011f) * 0.6f;
  animation.pupilRadius += (pupil - animation.pupilRadius) * (1.0f - expf(-dt * 5.0f));

  if ((int32_t)(now - nextMicroMs) >= 0) {
    uint32_t h = noiseHash(now);
    microTargetX = ((int)(h & 255) - 128) / 128.0f * 0.036f;
    microTargetY = ((int)((h >> 8) & 255) - 128) / 128.0f * 0.028f;
    nextMicroMs = now + 320 + (h % 1100);
  }
  float microFollow = min(1.0f, dt * 24.0f);
  animation.microX += (microTargetX - animation.microX) * microFollow;
  animation.microY += (microTargetY - animation.microY) * microFollow;
}

static float blinkOpenness(uint32_t now, int eyeIndex) {
  static uint32_t nextBlinkMs = 2800;
  static uint32_t blinkStartMs = 0;
  static bool blinking = false;
  if (eyeIndex == 0) {
    if (animation.acquisition > 0.3f && !blinking) nextBlinkMs = now + 1800;
    if (!blinking && (int32_t)(now - nextBlinkMs) >= 0) {
      blinkStartMs = now;
      blinking = true;
    }
    if (blinking && now - blinkStartMs >= 285) {
      blinking = false;
      nextBlinkMs = now + 2900 + (noiseHash(now) % 4800);
    }
  }
  if (!blinking) return 1.0f;
  int elapsed = (int)(now - blinkStartMs) - eyeIndex * 17;
  if (elapsed < 0) return 1.0f;
  // Fast close, an actual closed interval, slower release; 17ms lid lag.
  if (elapsed < 72) return 1.0f - smoothUnit(elapsed / 72.0f);
  if (elapsed < 120) return 0.0f;
  return smoothUnit((elapsed - 120) / 145.0f);
}

static void renderFrame() {
  if (!displayReady) return;
  static uint32_t previousMs = 0;
  uint32_t now = millis();
  float dt = clampf((now - previousMs) / 1000.0f, 0.001f, 0.12f);
  previousMs = now;
  updateEyeAnimation(now, dt);
  copyBackdropToBackBuffer();
  uint16_t* fb = (uint16_t*)dsi_getCurrentFrameBuffer();
  float lookX = gazeX + (manualGaze ? 0.0f : animation.microX);
  float lookY = gazeY + (manualGaze ? 0.0f : animation.microY);
  for (int e = 0; e < 2; ++e) {
    float open = animation.opening[e] * blinkOpenness(now, e);
    renderEye(fb, eyes[e], e, open, lookX, lookY);
  }
  // LTDC reads SDRAM, not the M7 cache. Without this, the eye rendered last
  // retains dirty pixels and the panel sees stale blocks (invisible in S dumps).
  // Clean the small physical cache by set/way, not all 24,000 framebuffer
  // addresses. This retains valid cache lines and is much cheaper per frame.
  SCB_CleanDCache();
  dsi_drawCurrentFrameBuffer();
}

// --------------------------------------------------------------------------
// Camera, person classification, and location tracking

static bool initMachineLearning() {
  tflite::InitializeTarget();
  model = tflite::GetModel(g_person_detect_model_data);
  if (!model || model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.print("[ml] model schema mismatch: model=");
    Serial.print(model ? model->version() : -1);
    Serial.print(" runtime=");
    Serial.println(TFLITE_SCHEMA_VERSION);
    return false;
  }

  static tflite::MicroMutableOpResolver<5> resolver;
  if (resolver.AddAveragePool2D() != kTfLiteOk ||
      resolver.AddConv2D() != kTfLiteOk ||
      resolver.AddDepthwiseConv2D() != kTfLiteOk ||
      resolver.AddReshape() != kTfLiteOk ||
      resolver.AddSoftmax() != kTfLiteOk) {
    Serial.println("[ml] failed to register operators");
    return false;
  }

  static tflite::MicroInterpreter staticInterpreter(
      model, resolver, tensorArena, TENSOR_ARENA_BYTES);
  interpreter = &staticInterpreter;
  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("[ml] AllocateTensors failed");
    return false;
  }

  modelInput = interpreter->input(0);
  modelOutput = interpreter->output(0);
  if (!modelInput || !modelOutput || modelInput->type != kTfLiteInt8 ||
      modelInput->dims->size != 4 || modelInput->dims->data[1] != MODEL_H ||
      modelInput->dims->data[2] != MODEL_W || modelInput->dims->data[3] != 1) {
    Serial.println("[ml] unexpected model tensors");
    return false;
  }
  Serial.print("[ml] ready, arena used <= ");
  Serial.print(TENSOR_ARENA_BYTES / 1024);
  Serial.println(" KB");
  return true;
}

static float outputValue(int index) {
  if (!modelOutput) return 0.0f;
  if (modelOutput->type == kTfLiteInt8) {
    return (modelOutput->data.int8[index] - modelOutput->params.zero_point) *
           modelOutput->params.scale;
  }
  if (modelOutput->type == kTfLiteUInt8) {
    return (modelOutput->data.uint8[index] - modelOutput->params.zero_point) *
           modelOutput->params.scale;
  }
  if (modelOutput->type == kTfLiteFloat32) return modelOutput->data.f[index];
  return 0.0f;
}

static void fillModelInput(InferenceView view, const uint8_t* frame) {
  int cropX = 40, cropY = 0, cropW = 240, cropH = 240;
  if (view == VIEW_LEFT) {
    cropX = 0; cropY = 15; cropW = 210; cropH = 210;
  } else if (view == VIEW_RIGHT) {
    cropX = 110; cropY = 15; cropW = 210; cropH = 210;
  }

  for (int oy = 0; oy < MODEL_H; ++oy) {
    int sy = cropY + (oy * cropH + cropH / (MODEL_H * 2)) / MODEL_H;
    sy = clampi(sy, 0, CAM_H - 1);
    for (int ox = 0; ox < MODEL_W; ++ox) {
      int sx = cropX + (ox * cropW + cropW / (MODEL_W * 2)) / MODEL_W;
      sx = clampi(sx, 0, CAM_W - 1);
      uint8_t pixel = frame[sy * CAM_W + sx];
      // This model's training pipeline maps camera bytes directly from
      // unsigned [0,255] to signed [-128,127]. Its input quantization metadata
      // describes the normalized training domain and must not be applied to
      // the raw byte again (that would saturate every pixel to +127).
      modelInput->data.int8[oy * MODEL_W + ox] = (int8_t)((int)pixel - 128);
    }
  }
}

static void runPersonInference(const uint8_t* frame) {
  if (!mlReady || !frame) return;
  InferenceView view = inferenceSequence[inferenceStep];
  inferenceStep = (inferenceStep + 1) % 4;
  fillModelInput(view, frame);

  uint32_t started = millis();
  if (interpreter->Invoke() != kTfLiteOk) {
    Serial.println("[ml] Invoke failed");
    return;
  }
  lastInferenceTimeMs = millis() - started;

  // Model labels are [not a person, person].
  float noPerson = outputValue(0);
  float person = outputValue(1);
  viewNoPerson[view] = noPerson;
  viewPerson[view] = person;
  viewUpdatedMs[view] = millis();

  float strongest = max(viewPerson[VIEW_FULL],
                         max(viewPerson[VIEW_LEFT], viewPerson[VIEW_RIGHT]));
  personConfidence = personConfidence * 0.72f + strongest * 0.28f;

  // The tiny 96x96 classifier can give moderately high scores to plain,
  // low-contrast walls. Only the full-frame view is allowed to acquire a
  // person: either its score is unequivocal, or a good score agrees with a
  // fresh, substantial moving silhouette. Once acquired, a lower score keeps
  // a stationary person locked. Ignore camera auto-exposure motion at boot.
  uint32_t now = millis();
  bool alreadyTracking = lastPersonSeenMs != 0 &&
                         now - lastPersonSeenMs < PERSON_HOLD_MS;
  bool freshMotion = now - lastUsefulMotionMs < 1000 && motionStrength > 80.0f;
  bool rawStrongPerson = person > PERSON_STRONG_THRESHOLD &&
                         person > noPerson + 0.10f;
  bool movingPerson = person > PERSON_MOVING_THRESHOLD &&
                      person > noPerson + 0.05f && freshMotion;
  bool keepPerson = alreadyTracking && person > 0.62f && person > noPerson;
  if (view == VIEW_FULL) {
    if (rawStrongPerson) {
      if (strongPersonStreak < 3) ++strongPersonStreak;
    } else {
      strongPersonStreak = 0;
    }
    bool confirmedStrongPerson = strongPersonStreak >= 2;
    if (now > 7000 && (confirmedStrongPerson || movingPerson || keepPerson)) {
      lastPersonSeenMs = now;
    }
  }
}

static void analyzeMotion(const uint8_t* frame) {
  uint8_t current[40 * 30];
  uint32_t sum = 0;
  for (int gy = 0; gy < 30; ++gy) {
    for (int gx = 0; gx < 40; ++gx) {
      int sx = gx * 8 + 4;
      int sy = gy * 8 + 4;
      int value = (frame[sy * CAM_W + sx] +
                   frame[sy * CAM_W + clampi(sx + 2, 0, CAM_W - 1)] +
                   frame[clampi(sy + 2, 0, CAM_H - 1) * CAM_W + sx]) / 3;
      current[gy * 40 + gx] = (uint8_t)value;
      sum += value;
    }
  }
  cameraAverage = (uint8_t)(sum / (40 * 30));

  if (!havePreviousGrid) {
    memcpy(previousGrid, current, sizeof(previousGrid));
    havePreviousGrid = true;
    return;
  }

  int meanDelta = 0;
  for (int i = 0; i < 40 * 30; ++i) meanDelta += (int)current[i] - previousGrid[i];
  meanDelta /= (40 * 30);

  uint32_t total = 0;
  uint32_t weightedX = 0, weightedY = 0;
  int activeCells = 0;
  for (int gy = 1; gy < 29; ++gy) {
    for (int gx = 1; gx < 39; ++gx) {
      int i = gy * 40 + gx;
      int delta = abs(((int)current[i] - previousGrid[i]) - meanDelta);
      if (delta > 12) {
        int weight = min(delta - 12, 55);
        total += weight;
        weightedX += weight * (gx * 8 + 4);
        weightedY += weight * (gy * 8 + 4);
        ++activeCells;
      }
    }
  }
  memcpy(previousGrid, current, sizeof(previousGrid));

  motionStrength = motionStrength * 0.70f + activeCells * 0.30f;
  if (total > 160 && activeCells >= 8) {
    float cx = weightedX / (float)total;
    float cy = weightedY / (float)total;
    motionX = motionX * 0.55f + cx * 0.45f;
    motionY = motionY * 0.62f + cy * 0.38f;
    lastUsefulMotionMs = millis();
  }
}

static void updateTracking(float dt) {
  uint32_t now = millis();
  humanPresent = lastPersonSeenMs != 0 && now - lastPersonSeenMs < PERSON_HOLD_MS;

  if (manualGaze) {
    targetGazeX = manualX;
    targetGazeY = manualY;
  } else if (humanPresent) {
    bool freshMotion = now - lastUsefulMotionMs < 1450;
    if (freshMotion) {
      targetGazeX = clampf((motionX - CAM_W * 0.5f) / (CAM_W * 0.43f), -1.0f, 1.0f);
      targetGazeY = clampf((motionY - CAM_H * 0.44f) / (CAM_H * 0.48f), -0.75f, 0.75f);
    } else {
      // The left/right person crops overlap. Their confidence difference gives
      // a stable coarse direction when the subject stands still.
      float l = viewPerson[VIEW_LEFT];
      float r = viewPerson[VIEW_RIGHT];
      float semanticX = (r - l) * 2.15f;
      targetGazeX = clampf(semanticX, -0.88f, 0.88f);
      targetGazeY *= 0.92f;
    }
  } else {
    // Nobody: return to a calm, nearly centered resting gaze.
    float idle = sinf(now * 0.00043f) * 0.055f;
    targetGazeX = idle;
    targetGazeY = sinf(now * 0.00031f + 1.2f) * 0.025f;
  }

  float follow = 1.0f - expf(-dt * (humanPresent ? 8.5f : 3.2f));
  gazeX += (targetGazeX - gazeX) * follow;
  gazeY += (targetGazeY - gazeY) * follow;
}

// --------------------------------------------------------------------------
// Serial diagnostics

static void dumpDisplay() {
  const uint8_t* fb = (const uint8_t*)dsi_getActiveFrameBuffer();
  Serial.print("FBSHOT 480 800 RGB565\n");
  Serial.flush();
  for (int offset = 0; offset < FB_W * FB_H * 2; offset += 8192) {
    int count = min(8192, FB_W * FB_H * 2 - offset);
    Serial.write(fb + offset, count);
  }
  Serial.print("\nFBDONE\n");
  Serial.flush();
}

static void dumpCamera() {
  if (!cameraReady || !cameraFrame.getBuffer()) return;
  Serial.print("CAMSHOT 320 240 GRAY8\n");
  Serial.flush();
  Serial.write(cameraFrame.getBuffer(), CAM_W * CAM_H);
  Serial.print("\nCAMDONE\n");
  Serial.flush();
}

static void printStatus() {
  Serial.print("[status] camera="); Serial.print(cameraReady);
  Serial.print(" ml="); Serial.print(mlReady);
  Serial.print(" human="); Serial.print(humanPresent);
  Serial.print(" confidence="); Serial.print(personConfidence, 3);
  Serial.print(" views=");
  Serial.print(viewPerson[VIEW_LEFT], 2); Serial.print('/');
  Serial.print(viewPerson[VIEW_FULL], 2); Serial.print('/');
  Serial.print(viewPerson[VIEW_RIGHT], 2);
  Serial.print(" motion="); Serial.print(motionX, 0); Serial.print(',');
  Serial.print(motionY, 0); Serial.print(" strength="); Serial.print(motionStrength, 1);
  Serial.print(" gaze="); Serial.print(gazeX, 2); Serial.print(','); Serial.print(gazeY, 2);
  Serial.print(" light="); Serial.print(cameraAverage);
  Serial.print(" infer_ms="); Serial.print(lastInferenceTimeMs);
  Serial.print(" fps="); Serial.println(renderFps, 1);
}

static char serialLine[40];
static uint8_t serialLength = 0;

static void handleSerialLine(const char* line) {
  if (line[0] == 'S') dumpDisplay();
  else if (line[0] == 'C') dumpCamera();
  else if (line[0] == 'I') printStatus();
  else if (line[0] == 'G') {
    int x, y;
    if (sscanf(line + 1, "%d %d", &x, &y) == 2) {
      if (x == 999 && y == 999) {
        manualGaze = false;
      } else {
        manualGaze = true;
        manualX = clampf(x / 100.0f, -1.0f, 1.0f);
        manualY = clampf(y / 100.0f, -1.0f, 1.0f);
      }
    }
  }
}

static void serviceSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialLength) {
        serialLine[serialLength] = 0;
        handleSerialLine(serialLine);
        serialLength = 0;
      }
    } else if (serialLength < sizeof(serialLine) - 1) {
      serialLine[serialLength++] = c;
    }
  }
}

// --------------------------------------------------------------------------
// Arduino lifecycle

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
  delay(300);
  Serial.println("\n[boot] GIGA Watching Eyes");
  Serial.println("[boot] probing the camera as OV7675...");

  camera.debug(Serial);
  cameraReady = camera.begin(CAMERA_R320x240, CAMERA_GRAYSCALE, 15);
  if (cameraReady) {
    camera.setHorizontalMirror(CAMERA_MIRROR_X);
    camera.setVerticalFlip(CAMERA_FLIP_Y);
    Serial.println("[camera] OV7675 ready at 320x240 grayscale / 15 fps");
  } else {
    Serial.println("[camera] ERROR: OV7675 was not detected");
  }

  int displayResult = Display.begin();
  displayReady = (displayResult == 0);
  __HAL_RCC_DMA2D_CLK_ENABLE();
  statusLed.begin();
  statusLed.off();

  if (displayReady) {
    backdrop = (uint16_t*)SDRAM.malloc(FB_W * FB_H * sizeof(uint16_t));
    openEyesBase = (uint16_t*)SDRAM.malloc(FB_W * FB_H * sizeof(uint16_t));
    buildBackdrop();
    buildOpenEyesBase();
    buildIrisTextures();

    if (cameraReady) {
      uint8_t* raw = (uint8_t*)SDRAM.malloc(CAM_W * CAM_H + 32);
      uint8_t* aligned = (uint8_t*)(((uintptr_t)raw + 31U) & ~((uintptr_t)31U));
      cameraFrame.setBuffer(aligned);
    }

    renderFrame();
    renderFrame();
  } else {
    Serial.print("[display] ERROR code "); Serial.println(displayResult);
  }

  mlReady = initMachineLearning();
  digitalWrite(LED_BUILTIN, cameraReady && mlReady && displayReady ? HIGH : LOW);
  lastLoopUs = micros();
  lastCaptureMs = millis() - CAPTURE_PERIOD_MS;
  lastInferenceMs = millis() - INFERENCE_PERIOD_MS;
  Serial.println("[boot] ready; send I for status, S for screen, C for camera");
}

void loop() {
  uint32_t nowUs = micros();
  float dt = (nowUs - lastLoopUs) / 1000000.0f;
  lastLoopUs = nowUs;
  dt = clampf(dt, 0.001f, 0.12f);
  float instantFps = 1.0f / dt;
  renderFps = renderFps * 0.94f + instantFps * 0.06f;

  serviceSerial();
  uint32_t now = millis();

  if (cameraReady && now - lastCaptureMs >= CAPTURE_PERIOD_MS) {
    lastCaptureMs = now;
    int result = camera.grabFrame(cameraFrame, 350);
    if (result == 0) {
      const uint8_t* frame = cameraFrame.getBuffer();
      analyzeMotion(frame);
      if (mlReady && now - lastInferenceMs >= INFERENCE_PERIOD_MS) {
        lastInferenceMs = now;
        runPersonInference(frame);
      }
    }
  }

  updateTracking(dt);
  renderFrame();

  if (now - lastStatusMs >= 5000) {
    lastStatusMs = now;
    printStatus();
  }
}

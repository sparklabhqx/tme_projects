#!/usr/bin/env python3
"""Exercise the sketch's actual C++ renderer on the host (NOT a hardware test).

Requires clang++ and Pillow. Outputs native RGB565, PNG previews and a contact
sheet under build/validation/host. Only DMA2D/SDRAM/display/time are stubbed;
all eye geometry, textures, clipping and animation come from the .ino.
"""
from pathlib import Path
import re
import subprocess
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/validation/host"

PREAMBLE = r"""
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
using std::min;
using std::max;
static constexpr float PI = 3.14159265358979323846f;
static uint32_t clockMs = 0;
static uint32_t millis() { return clockMs; }
static bool displayReady = true;
static void dumpDisplay() {}
static void dumpCamera() {}
static void printStatus() {}
struct HostSDRAM { void* malloc(size_t bytes) { return std::malloc(bytes); } } SDRAM;
alignas(32) static uint16_t framebuffer[480 * 800];
static void* dsi_getCurrentFrameBuffer() { return framebuffer; }

// Mock the hardware, not the transfer wrapper: assert real cache ownership
// transitions and aligned ranges. The board audit additionally tests real RAM.
struct CleanRange { uintptr_t address; size_t bytes; };
static std::vector<CleanRange> cacheCleans;
static int dmaStage = 0, dmaTransfers = 0, presentations = 0;
static bool framePublished = false;
static void SCB_CleanDCache_by_Addr(uint32_t* address, int32_t bytes) {
  assert(((uintptr_t)address & 31) == 0 && bytes > 0 && (bytes & 31) == 0);
  cacheCleans.push_back({(uintptr_t)address, (size_t)bytes});
  if ((void*)address == framebuffer && bytes == sizeof(framebuffer)) {
    assert(dmaStage == 0);
    framePublished = true;
  }
}
static void SCB_CleanDCache() {
  assert(dmaStage == 0);
  framePublished = true;
}
static void SCB_InvalidateDCache_by_Addr(uint32_t* address, int32_t bytes) {
  assert((void*)address == framebuffer && bytes == sizeof(framebuffer));
  assert(((uintptr_t)address & 31) == 0 && (bytes & 31) == 0);
  assert(dmaStage == 0 || dmaStage == 3);
  dmaStage = dmaStage == 0 ? 1 : 0; // before DMA or after DMA completion
  framePublished = false;
}
static constexpr int DMA2D = 1, DMA2D_M2M = 2, DMA2D_OUTPUT_RGB565 = 3;
static constexpr int DMA2D_INPUT_RGB565 = 3, DMA2D_NO_MODIF_ALPHA = 4;
struct DMA2D_HandleTypeDef {
  int Instance;
  struct { int Mode, ColorMode, OutputOffset; } Init;
  struct { int AlphaMode, InputAlpha, InputColorMode, InputOffset; } LayerCfg[2];
};
static int HAL_DMA2D_Init(DMA2D_HandleTypeDef*) { return 0; }
static int HAL_DMA2D_ConfigLayer(DMA2D_HandleTypeDef*, int) { return 0; }
static int HAL_DMA2D_Start(DMA2D_HandleTypeDef*, uintptr_t src, uintptr_t dst, int w, int h) {
  assert(dmaStage == 1 && dst == (uintptr_t)framebuffer && w == 480 && h == 800);
  bool sourcePublished = false;
  for (const auto& range : cacheCleans) {
    sourcePublished |= range.address <= src && range.address + range.bytes >= src + sizeof(framebuffer);
  }
  assert(sourcePublished); // immutable SDRAM base must be cleaned once before DMA
  memcpy((void*)dst, (void*)src, w * h * sizeof(uint16_t));
  dmaStage = 2;
  ++dmaTransfers;
  return 0;
}
static int HAL_DMA2D_PollForTransfer(DMA2D_HandleTypeDef*, int) {
  assert(dmaStage == 2);
  dmaStage = 3;
  return 0;
}
static void dsi_drawCurrentFrameBuffer() {
  assert(dmaStage == 0 && framePublished); // CPU render was cleaned before scanout
  framePublished = false;
  ++presentations;
}
"""

MAIN = r"""
static void checkBlackOutside(float open) {
  size_t lit = 0;
  for (int x = 0; x < SCREEN_W; ++x) {
    for (int y = 0; y < SCREEN_H; ++y) {
      uint16_t pixel = *landscapePixel(framebuffer, x, y);
      if (!insideEye(0, x, y) && !insideEye(1, x, y)) assert(pixel == 0);
      if (open == 0) assert(pixel == 0);
      lit += pixel != 0;
    }
  }
  if (open > 0.1f) assert(lit > 500);
}
static void snapshot(const char* name) {
  std::string path = std::string(name) + ".rgb565";
  FILE* f = fopen(path.c_str(), "wb");
  assert(f);
  assert(fwrite(framebuffer, sizeof(framebuffer), 1, f) == 1);
  fclose(f);
}
static void fixedFrame(float open, float gx, float gy, int pupil) {
  copyBackdropToBackBuffer();
  animation.pupilRadius = pupil;
  for (int e = 0; e < 2; ++e) renderEye(framebuffer, eyes[e], e, open, gx, gy);
  checkBlackOutside(open);
  // Stronger than bounding-box testing: EVERY covered lid pixel must be black.
  for (int e = 0; e < 2; ++e) {
    const EyeContour& c = contours[e];
    for (int i = 0; i < EYE_COLUMNS; ++i) {
      int seam = c.seam[i] + 9;
      int top = clampi(c.top[i] + (int)((seam - c.top[i]) * (1 - open)), c.top[i], c.bottom[i]);
      int bot = clampi(c.bottom[i] - (int)((c.bottom[i] - seam) * (1 - open)), c.top[i], c.bottom[i]);
      bool empty = bot - top < 3 || open < 0.025f || i == 0 || i == EYE_COLUMNS - 1;
      for (int y = c.top[i]; y <= c.bottom[i]; ++y) {
        if (empty || y < top || y > bot) {
          assert(*landscapePixel(framebuffer, eyes[e].cx - eyes[e].rx + i, y) == 0);
        }
      }
    }
  }
}
static void testGazeControl() {
  // Exercise the actual updateTracking function, including uint32 millis wrap.
  for (uint32_t start : {1000U, UINT32_MAX - 10000U}) {
    clockMs = start;
    manualGaze = false;
    lastPersonSeenMs = 0;
    gazeX = 0.9f; gazeY = 0.0f;
    // With nobody present the gaze must ease back to the near-center idle.
    for (int n = 0; n < 200; ++n) {
      clockMs += 50;
      updateTracking(0.05f);
      assert(gazeX >= -1 && gazeX <= 1 && gazeY >= -1 && gazeY <= 1);
    }
    assert(fabsf(gazeX) < 0.06f);
  }
  clockMs = 1000;
  manualGaze = false;
  handleSerialLine("G -100 75");
  updateTracking(0.05f);
  assert(manualGaze && targetGazeX == -1 && targetGazeY == 0.75f);
  handleSerialLine("G 999 999");
  updateTracking(0.05f);
  assert(!manualGaze && fabsf(targetGazeX) < 0.06f);
  puts("PASS: idle easing, millis wraparound, manual G gaze and return to camera");
  gazeX = gazeY = 0;
}
int main() {
  testGazeControl();
  backdrop = (uint16_t*)SDRAM.malloc(sizeof(framebuffer));
  openEyesBase = (uint16_t*)SDRAM.malloc(sizeof(framebuffer));
  assert(backdrop && openEyesBase);
  buildBackdrop(); buildOpenEyesBase(); buildIrisTextures();
  for (uint16_t* p = backdrop; p < backdrop + FB_W * FB_H; ++p) assert(*p == 0);
  for (int e = 0; e < 2; ++e) {
    assert(irisTexture[e]);
    assert(eyes[e].rx * 2 + 1 == EYE_COLUMNS);
    for (int i = 0; i < EYE_COLUMNS; ++i) {
      assert(contours[e].top[i] >= 0 && contours[e].bottom[i] < SCREEN_H);
      assert(contours[e].top[i] <= contours[e].bottom[i]);
    }
  }
  for (float open : {0.0f, 0.01f, 0.03f, 0.15f, 0.45f, 0.74f, 1.0f}) {
    for (float gx : {-1.0f, 0.0f, 1.0f}) for (float gy : {-1.0f, 0.0f, 1.0f}) {
      for (int pupil : {22, 29, 43}) fixedFrame(open, gx, gy, pupil);
    }
  }
  puts("PASS: 189 aperture/gaze/pupil combinations; exterior and closed masks = 0x0000");
  fixedFrame(1, 0, 0, 29); snapshot("open_center");
  fixedFrame(0.74f, 0, 0, 29); snapshot("idle");
  fixedFrame(1, 0, 0, 40); snapshot("acquired");
  fixedFrame(0.45f, 0, 0, 29); snapshot("narrow");
  fixedFrame(0, 0, 0, 29); snapshot("closed");
  const char* names[3][3] = {{"gaze_left_up", "gaze_left", "gaze_left_down"},
                            {"gaze_up", "gaze_center", "gaze_down"},
                            {"gaze_right_up", "gaze_right", "gaze_right_down"}};
  for (int x = -1; x <= 1; ++x) for (int y = -1; y <= 1; ++y) {
    fixedFrame(1, x, y, 29); snapshot(names[x+1][y+1]);
  }
  // Exercise production animation state with a synthetic presence transition.
  // This does NOT claim that the actual camera acquired a human.
  for (clockMs = 0; clockMs < 10000; clockMs += 20) updateEyeAnimation(clockMs, 0.02f);
  assert(animation.acquisition == 0 && animation.opening[0] < 0.8f);
  humanPresent = true;
  float idlePupil = animation.pupilRadius;
  for (; clockMs < 10400; clockMs += 20) updateEyeAnimation(clockMs, 0.02f);
  assert(animation.acquisition > 0.85f && animation.opening[0] > 0.97f);
  assert(animation.pupilRadius > idlePupil + 7);
  for (; clockMs < 14000; clockMs += 20) updateEyeAnimation(clockMs, 0.02f);
  assert(animation.acquisition == 0 && animation.opening[0] < 0.90f);
  humanPresent = false;
  manualGaze = true;
  for (; clockMs < 16000; clockMs += 20) updateEyeAnimation(clockMs, 0.02f);
  assert(animation.opening[0] > 0.99f && animation.opening[1] > 0.99f);
  manualGaze = false;
  bool bothClosed = false, asynchronous = false;
  // Blink helper's first use: due at 2800ms, then inspect at 1ms resolution.
  animation.acquisition = 0;
  for (uint32_t t = 2800; t <= 3100; ++t) {
    float a = blinkOpenness(t, 0), b = blinkOpenness(t, 1);
    assert(a >= 0 && a <= 1 && b >= 0 && b <= 1);
    bothClosed |= a == 0 && b == 0;
    asynchronous |= fabsf(a - b) > 0.1f;
  }
  assert(bothClosed && asynchronous);
  puts("PASS: synthetic acquisition/dilation/settling, manual opening, asymmetric full blink");
  for (int frame = 0; frame < 65; ++frame) {
    clockMs = 20000 + frame * 60;
    renderFrame();
    checkBlackOutside(-1);
    char name[32]; snprintf(name, sizeof(name), "animation_%03d", frame);
    snapshot(name);
  }
  puts("PASS: production renderFrame timeline; no out-of-aperture pixels");
  alignas(32) uint8_t unalignedProbe[96];
  cleanDisplayCache(unalignedProbe + 3, 34);
  assert(cacheCleans.back().address == (uintptr_t)unalignedProbe && cacheCleans.back().bytes == 64);
  assert(dmaTransfers > 200 && presentations == 65 && dmaStage == 0);
  puts("PASS: cache range alignment, static-base publish, DMA invalidation order, clean before present");
  return 0;
}
"""


def decode_rgb565(data):
    """Native (480 x 800): landscape (x,y) = native (479-y,x)."""
    rgb = bytearray(len(data) // 2 * 3)
    for i in range(0, len(data), 2):
        word = data[i] | data[i + 1] << 8
        j = i // 2 * 3
        rgb[j:j + 3] = bytes((((word >> 11) & 31) * 255 // 31,
                              ((word >> 5) & 63) * 255 // 63,
                              (word & 31) * 255 // 31))
    return Image.frombytes("RGB", (480, 800), bytes(rgb)).transpose(Image.Transpose.ROTATE_90)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sketch = (ROOT / "giga_watching_eyes.ino").read_text()
    constants = "\n".join(re.findall(
        r"static constexpr (?:int|uint32_t) (?:SCREEN_[WH]|FB_[WH]|CAM_[WH]|PERSON_HOLD_MS) = .*?;", sketch))
    tracking_state = sketch[sketch.index("enum InferenceView"):sketch.index("// Rendering storage and helpers")]
    tracking = sketch[sketch.index("static void updateTracking("):sketch.index("// Serial diagnostics")]
    serial_handler = sketch[sketch.index("static void handleSerialLine("):sketch.index("static void serviceSerial(")]
    renderer = sketch[sketch.index("static uint16_t* backdrop"):sketch.index("// Camera, person classification")]
    # Keep the actual DMA/cache wrapper; only widen hardware pointer arguments
    # for the 64-bit host. HAL/SCB calls themselves are mocked above.
    renderer = renderer.replace("(uint32_t)source", "(uintptr_t)source")
    renderer = renderer.replace("(uint32_t)dst", "(uintptr_t)dst")
    cpp = OUT / "renderer_test.cpp"
    cpp.write_text(PREAMBLE + constants + "\n" + tracking_state + renderer + tracking + serial_handler + MAIN)
    subprocess.run(["clang++", "-std=c++17", "-O2", "-fsanitize=address,undefined", "-g",
                    str(cpp), "-o", str(OUT / "renderer_test")], check=True)
    subprocess.run([str(OUT / "renderer_test")], cwd=OUT, check=True)
    for path in OUT.glob("*.rgb565"):
        decode_rgb565(path.read_bytes()).save(path.with_suffix(".png"))
    names = ["idle", "open_center", "acquired", "narrow", "gaze_left_up", "gaze_right_down"]
    sheet = Image.new("RGB", (800, 3 * 265), "#161616")
    draw = ImageDraw.Draw(sheet)
    for i, name in enumerate(names):
        xy = (i % 2 * 400, i // 2 * 265)
        image = Image.open(OUT / f"{name}.png").resize((400, 240))
        sheet.paste(image, xy)
        draw.text((xy[0] + 8, xy[1] + 243), "HOST: " + name, fill="white")
    sheet.save(OUT / "contact_sheet.png")
    frames = [Image.open(path).resize((800, 480)) for path in sorted(OUT.glob("animation_*.png"))]
    frames[0].save(OUT / "animation.gif", save_all=True, append_images=frames[1:], duration=60, loop=0)
    print(f"Host previews (not hardware captures): {OUT}")


if __name__ == "__main__":
    main()

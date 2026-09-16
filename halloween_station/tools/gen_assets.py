#!/usr/bin/env python3
"""Halloween Gaming Station — asset generator.

Draws all sprites with pycairo (2x supersampled), converts to the GIGA
Display's portrait memory layout (pre-rotated 90° CW), and emits C arrays:
  ARGB4444  — full-colour sprites with alpha (DMA2D blended)
  A8        — masks tinted at runtime via DMA2D FGCOLR (glows, silhouettes, text)
  RGB565    — opaque images

Also writes tools/preview/*.png and a combined sprite sheet for visual QA.
"""
import cairo, math, random, os, sys
import numpy as np

OUT = os.path.dirname(os.path.abspath(__file__))
PREV = os.path.join(OUT, "preview")
SRC = os.path.dirname(OUT)  # sketch root
os.makedirs(PREV, exist_ok=True)
random.seed(1031)

SS = 2  # supersample factor

# ---------------------------------------------------------------- helpers

def make_ctx(w, h):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w * SS, h * SS)
    ctx = cairo.Context(surf)
    ctx.scale(SS, SS)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    return surf, ctx

def downsample(surf, w, h):
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    c = cairo.Context(out)
    c.scale(1.0 / SS, 1.0 / SS)
    c.set_source_surface(surf, 0, 0)
    c.get_source().set_filter(cairo.FILTER_BEST)
    c.paint()
    return out

def surf_to_rgba(surf):
    """ARGB32 premultiplied -> straight RGBA uint8 (h, w, 4)."""
    surf.flush()
    w, h = surf.get_width(), surf.get_height()
    buf = np.ndarray(shape=(h, surf.get_stride() // 4, 4), dtype=np.uint8,
                     buffer=surf.get_data())[:, :w, :]
    b, g, r, a = [buf[:, :, i].astype(np.float32) for i in range(4)]
    an = np.maximum(a, 1.0)
    r = np.clip(r / an * 255.0, 0, 255)
    g = np.clip(g / an * 255.0, 0, 255)
    b = np.clip(b / an * 255.0, 0, 255)
    return np.stack([r, g, b, a], axis=-1).astype(np.uint8)

def rgba_to_argb4444_portrait(rgba):
    p = np.rot90(rgba, -1)  # landscape -> portrait (90 deg CW)
    r = (p[:, :, 0].astype(np.uint16) >> 4)
    g = (p[:, :, 1].astype(np.uint16) >> 4)
    b = (p[:, :, 2].astype(np.uint16) >> 4)
    a = (p[:, :, 3].astype(np.uint16) >> 4)
    return (a << 12) | (r << 8) | (g << 4) | b

def rgba_to_a8_portrait(rgba):
    return np.rot90(rgba[:, :, 3], -1).copy()

def rgba_to_rgb565_portrait(rgba):
    p = np.rot90(rgba, -1)
    r = (p[:, :, 0].astype(np.uint16) >> 3)
    g = (p[:, :, 1].astype(np.uint16) >> 2)
    b = (p[:, :, 2].astype(np.uint16) >> 3)
    return (r << 11) | (g << 5) | b

def save_png(surf, name):
    surf.write_to_png(os.path.join(PREV, name + ".png"))

SPRITES = []  # (name, fmt, portrait_array, lw, lh)

def add_sprite(name, surf, fmt="argb4444"):
    lw, lh = surf.get_width(), surf.get_height()
    rgba = surf_to_rgba(surf)
    if fmt == "argb4444":
        arr = rgba_to_argb4444_portrait(rgba)
    elif fmt == "a8":
        arr = rgba_to_a8_portrait(rgba)
    elif fmt == "rgb565":
        arr = rgba_to_rgb565_portrait(rgba)
    else:
        raise ValueError(fmt)
    SPRITES.append((name, fmt, arr, lw, lh))
    save_png(surf, name)

def sprite(name, w, h, fmt="argb4444"):
    """Decorator: draw fn receives (ctx, w, h); auto down/convert/register."""
    def deco(fn):
        surf, ctx = make_ctx(w, h)
        fn(ctx, w, h)
        add_sprite(name, downsample(surf, w, h), fmt)
        return fn
    return deco

def rad_grad(cx, cy, r, stops):
    g = cairo.RadialGradient(cx, cy, r * 0.05, cx, cy, r)
    for off, col in stops:
        g.add_color_stop_rgba(off, *col)
    return g

def lin_grad(x0, y0, x1, y1, stops):
    g = cairo.LinearGradient(x0, y0, x1, y1)
    for off, col in stops:
        g.add_color_stop_rgba(off, *col)
    return g

def C(hexs, a=1.0):
    hexs = hexs.lstrip('#')
    return (int(hexs[0:2], 16) / 255, int(hexs[2:4], 16) / 255,
            int(hexs[4:6], 16) / 255, a)

# ---------------------------------------------------------------- pumpkin

def pumpkin_body(ctx, w, h, bright):
    """Shared jack-o'-lantern body + face. bright: 0 dim glow, 1 bright."""
    cx, cy = w / 2, h * 0.56
    bw, bh = w * 0.46, h * 0.40   # half extents of body
    # stem
    ctx.save()
    ctx.translate(cx, cy - bh * 0.92)
    ctx.rotate(-0.18)
    stem = lin_grad(-6, -h*0.16, 8, 0, [(0, C('#5d8a33')), (1, C('#39571e'))])
    ctx.set_source(stem)
    ctx.move_to(-w*0.045, 4)
    ctx.curve_to(-w*0.06, -h*0.10, -w*0.015, -h*0.16, w*0.02, -h*0.155)
    ctx.curve_to(w*0.055, -h*0.15, w*0.05, -h*0.06, w*0.045, 6)
    ctx.close_path()
    ctx.fill_preserve()
    ctx.set_source_rgba(*C('#24380f'))
    ctx.set_line_width(2.6)
    ctx.stroke()
    ctx.restore()
    # body lobes, back to front
    lobes = [(0.0, 1.0), (-0.62, 0.82), (0.62, 0.82), (-0.33, 0.95), (0.33, 0.95)]
    for i, (off, s) in enumerate(lobes):
        lx = cx + off * bw
        g = rad_grad(lx - bw*0.12, cy - bh*0.35, bw * 1.25, [
            (0, C('#ffab3d')), (0.55, C('#f57f17')), (0.85, C('#c85f06')), (1, C('#9a4404'))])
        ctx.set_source(g)
        ctx.save()
        ctx.translate(lx, cy)
        ctx.scale(s * bw * 0.62, bh)
        ctx.arc(0, 0, 1, 0, 2 * math.pi)
        ctx.restore()
        ctx.fill()
    # outline
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(bw * 1.02, bh * 1.005)
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()
    ctx.set_source_rgba(*C('#6e2f03'))
    ctx.set_line_width(3.2)
    ctx.stroke()
    # lobe creases
    ctx.set_line_width(2.2)
    ctx.set_source_rgba(*C('#a85405', 0.75))
    for off in (-0.62, -0.33, 0.33, 0.62):
        ctx.save()
        ctx.translate(cx + off * bw * 0.72, cy)
        ctx.scale(abs(off) * bw * 0.55 + bw * 0.18, bh * 0.94)
        ctx.arc(0, 0, 1, -1.35, 1.35) if off > 0 else ctx.arc(0, 0, 1, math.pi - 1.35, math.pi + 1.35)
        ctx.restore()
        ctx.stroke()
    # face: eyes, nose, mouth — glowing
    glow_in = C('#fff3a6') if bright else C('#ffd23f')
    glow_out = C('#ff9800') if bright else C('#f57f17')
    face = rad_grad(cx, cy + bh*0.05, bw * 0.9, [(0, glow_in), (1, glow_out)])
    def tri(x, y, s, flip=1):
        ctx.move_to(x - s, y + s * 0.72)
        ctx.line_to(x + s, y + s * 0.72)
        ctx.line_to(x + s * 0.12 * flip, y - s * 0.85)
        ctx.close_path()
    ctx.set_source(face)
    tri(cx - bw * 0.42, cy - bh * 0.18, bw * 0.22)      # left eye
    tri(cx + bw * 0.42, cy - bh * 0.18, bw * 0.22, -1)  # right eye
    tri(cx, cy + bh * 0.10, bw * 0.11)                  # nose
    ctx.fill()
    # jagged grin
    ctx.set_source(face)
    mx, my, mw2 = cx, cy + bh * 0.47, bw * 0.62
    ctx.move_to(mx - mw2, my - bh * 0.10)
    ctx.curve_to(mx - mw2 * 0.5, my + bh * 0.22, mx + mw2 * 0.5, my + bh * 0.22, mx + mw2, my - bh * 0.10)
    # top edge with two notches (teeth)
    ctx.line_to(mx + mw2 * 0.62, my - bh * 0.04)
    ctx.line_to(mx + mw2 * 0.48, my - bh * 0.16)
    ctx.line_to(mx + mw2 * 0.34, my - bh * 0.02)
    ctx.line_to(mx - mw2 * 0.20, my - bh * 0.02)
    ctx.line_to(mx - mw2 * 0.34, my - bh * 0.16)
    ctx.line_to(mx - mw2 * 0.48, my - bh * 0.02)
    ctx.close_path()
    ctx.fill()

@sprite("spr_pumpkin0", 132, 116)
def _(ctx, w, h): pumpkin_body(ctx, w, h, 0)

@sprite("spr_pumpkin1", 132, 116)
def _(ctx, w, h): pumpkin_body(ctx, w, h, 1)

@sprite("spr_pumpkin_squash", 148, 92)
def _(ctx, w, h):
    ctx.save(); ctx.scale(148/132, 92/116); pumpkin_body(ctx, 132, 116, 1); ctx.restore()

@sprite("spr_pumpkin_stretch", 116, 130)
def _(ctx, w, h):
    ctx.save(); ctx.scale(116/132, 130/116); pumpkin_body(ctx, 132, 116, 0); ctx.restore()

# ---------------------------------------------------------------- splat

def goo_blob(ctx, cx, cy, rr, n, spikes, seedoff=0):
    rnd = random.Random(77 + seedoff)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        r = rr * (1.0 + (spikes if i % 2 == 0 else 0) * (0.55 + rnd.random() * 0.5))
        pts.append((cx + math.cos(a) * r * 1.45, cy + math.sin(a) * r * 0.75))
    ctx.move_to(*pts[0])
    for i in range(1, n + 1):
        x0, y0 = pts[(i - 1) % n]; x1, y1 = pts[i % n]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ctx.curve_to(x0 + (mx-x0)*0.6, y0 + (my-y0)*0.6, x1 + (mx-x1)*0.6, y1 + (my-y1)*0.6, x1, y1)
    ctx.close_path()

@sprite("spr_splat0", 164, 96)
def _(ctx, w, h):
    cx, cy = w/2, h*0.55
    g = rad_grad(cx, cy, w*0.5, [(0, C('#ffa63f')), (0.6, C('#f57f17')), (1, C('#c85f06'))])
    ctx.set_source(g); goo_blob(ctx, cx, cy, w*0.20, 16, 0.9)
    ctx.fill_preserve(); ctx.set_source_rgba(*C('#6e2f03')); ctx.set_line_width(3); ctx.stroke()
    rnd = random.Random(5)
    ctx.set_source_rgba(*C('#ffe9b8'))
    for i in range(7):  # seeds
        a = rnd.random()*2*math.pi; r = rnd.random()*w*0.16
        ctx.save(); ctx.translate(cx+math.cos(a)*r*1.5, cy+math.sin(a)*r*0.7); ctx.rotate(rnd.random()*3)
        ctx.scale(5, 3.4); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()

@sprite("spr_splat1", 164, 84)
def _(ctx, w, h):
    cx, cy = w/2, h*0.52
    g = rad_grad(cx, cy, w*0.5, [(0, C('#e08922')), (0.7, C('#c26a0e')), (1, C('#8f4a06'))])
    ctx.set_source(g); goo_blob(ctx, cx, cy, w*0.22, 14, 0.55, 3)
    ctx.fill_preserve(); ctx.set_source_rgba(*C('#5c2703')); ctx.set_line_width(3); ctx.stroke()
    rnd = random.Random(9)
    ctx.set_source_rgba(*C('#f0d9a8'))
    for i in range(5):
        a = rnd.random()*2*math.pi; r = rnd.random()*w*0.15
        ctx.save(); ctx.translate(cx+math.cos(a)*r*1.5, cy+math.sin(a)*r*0.7)
        ctx.scale(4.4, 3); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()

for ci in range(3):
    @sprite(f"spr_chunk{ci}", 26, 22)
    def _(ctx, w, h, ci=ci):
        rnd = random.Random(40 + ci)
        g = rad_grad(w*0.4, h*0.35, w*0.6, [(0, C('#ffab3d')), (1, C('#b55405'))])
        ctx.set_source(g); goo_blob(ctx, w/2, h/2, w*0.22, 8, 0.5, 60+ci)
        ctx.fill_preserve(); ctx.set_source_rgba(*C('#6e2f03')); ctx.set_line_width(2); ctx.stroke()

# ---------------------------------------------------------------- bat

def bat_draw(ctx, w, h, phase):
    """phase 0=wings up, 1=mid, 2=down"""
    cx, cy = w/2, h*0.52
    ang = [-0.38, -0.05, 0.30][phase]  # wing rotation about shoulder
    body_grad = rad_grad(cx, cy - h*0.1, w*0.3, [(0, C('#8a6fc0')), (0.55, C('#5d4790')), (1, C('#32245c'))])
    def wing(sgn):
        ctx.save()
        ctx.translate(cx + sgn * w*0.075, cy - h*0.05)  # shoulder
        ctx.rotate(sgn * ang)
        ctx.scale(sgn, 1)
        # wing in local coords: shoulder at (0,0), tip out at +x
        WL = w * 0.42          # wing length
        ctx.move_to(0, 0)
        # top edge: two humps (finger joints) to the tip
        ctx.curve_to(WL*0.22, -h*0.34, WL*0.42, -h*0.30, WL*0.55, -h*0.16)
        ctx.curve_to(WL*0.75, -h*0.26, WL*0.95, -h*0.16, WL, h*0.02)
        # scalloped bottom edge: 3 membrane arcs back to the body
        ctx.curve_to(WL*0.86, h*0.02, WL*0.80, h*0.14, WL*0.72, h*0.30)
        ctx.curve_to(WL*0.62, h*0.16, WL*0.52, h*0.16, WL*0.42, h*0.34)
        ctx.curve_to(WL*0.32, h*0.18, WL*0.20, h*0.16, WL*0.09, h*0.26)
        ctx.curve_to(WL*0.04, h*0.18, 0.0, h*0.10, 0, h*0.06)
        ctx.close_path()
        ctx.set_source(body_grad)
        ctx.fill_preserve()
        ctx.set_source_rgba(*C('#120b22')); ctx.set_line_width(2.6); ctx.stroke()
        # finger bones
        ctx.set_source_rgba(*C('#171028', 0.55)); ctx.set_line_width(1.8)
        for fx, fy in ((0.55, -0.16), (0.72, 0.24), (0.42, 0.28)):
            ctx.move_to(0, 0); ctx.line_to(WL*fx, h*fy); ctx.stroke()
        ctx.restore()
    wing(-1); wing(1)
    # body
    ctx.set_source(body_grad)
    ctx.save(); ctx.translate(cx, cy); ctx.scale(w*0.115, h*0.30); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore()
    ctx.fill_preserve()
    ctx.set_source_rgba(*C('#120b22')); ctx.set_line_width(2.6); ctx.stroke()
    # head + ears
    hy = cy - h*0.30
    ctx.set_source(body_grad)
    ctx.arc(cx, hy, w*0.10, 0, 2*math.pi); ctx.fill_preserve()
    ctx.set_source_rgba(*C('#120b22')); ctx.stroke()
    ctx.set_source(body_grad)
    for sgn in (-1, 1):
        ctx.move_to(cx + sgn*w*0.028, hy - w*0.075)
        ctx.line_to(cx + sgn*w*0.105, hy - w*0.175)
        ctx.line_to(cx + sgn*w*0.098, hy - w*0.028)
        ctx.close_path()
    ctx.fill_preserve(); ctx.set_source_rgba(*C('#120b22')); ctx.set_line_width(2); ctx.stroke()
    # eyes
    ctx.set_source_rgba(*C('#ffd93b'))
    for sgn in (-1, 1):
        ctx.arc(cx + sgn*w*0.045, hy - h*0.015, w*0.022, 0, 2*math.pi); ctx.fill()
    ctx.set_source_rgba(*C('#1a1206'))
    for sgn in (-1, 1):
        ctx.arc(cx + sgn*w*0.045 + w*0.006, hy - h*0.015, w*0.009, 0, 2*math.pi); ctx.fill()
    # fangs
    ctx.set_source_rgba(*C('#f5f5f0'))
    for sgn in (-1, 1):
        ctx.move_to(cx + sgn*w*0.03, hy + w*0.075)
        ctx.line_to(cx + sgn*w*0.014, hy + w*0.075)
        ctx.line_to(cx + sgn*w*0.023, hy + w*0.115)
        ctx.close_path()
    ctx.fill()

for ph in range(3):
    @sprite(f"spr_bat{ph}", 100, 68)
    def _(ctx, w, h, ph=ph): bat_draw(ctx, w, h, ph)

for ph in range(3):  # small silhouette bats (A8, tinted at runtime)
    @sprite(f"spr_bat_s{ph}", 44, 30, "a8")
    def _(ctx, w, h, ph=ph):
        ctx.push_group()
        bat_draw(ctx, w, h, ph)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(1.0)

# ---------------------------------------------------------------- ghost

def ghost_draw(ctx, w, h, sway):
    cx = w/2
    top = h*0.30
    g = lin_grad(cx - w*0.3, 0, cx + w*0.45, h, [(0, C('#ffffff', 0.94)), (0.55, C('#dfe6ff', 0.9)), (1, C('#aab6e8', 0.85))])
    ctx.set_source(g)
    ctx.move_to(cx - w*0.36, h*0.86)
    ctx.curve_to(cx - w*0.44, h*0.45, cx - w*0.34, top - h*0.16, cx, top - h*0.17)
    ctx.curve_to(cx + w*0.34, top - h*0.16, cx + w*0.44, h*0.45, cx + w*0.36, h*0.84)
    # wavy hem
    n = 4
    for i in range(n):
        t = i / n
        x1 = cx + w*0.36 - (t + 0.5/n) * w*0.72
        x0 = cx + w*0.36 - (t + 1.0/n) * w*0.72
        dip = h*0.06 if (i % 2 == 0) else -h*0.02
        ctx.curve_to(x1 + w*0.05, h*0.86 + dip + sway*h*0.03, x1 - w*0.05, h*0.86 + dip - sway*h*0.03, x0, h*0.84 + (0 if i == n-1 else dip*0.4))
    ctx.close_path()
    ctx.fill()
    # arms
    ctx.set_source(g)
    for sgn in (-1, 1):
        ay = h*0.48 + sgn * sway * h * 0.02
        ctx.save(); ctx.translate(cx + sgn*w*0.40, ay); ctx.rotate(sgn*0.5)
        ctx.scale(w*0.10, h*0.06); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    # face
    ctx.set_source_rgba(*C('#232c4d'))
    for sgn in (-1, 1):
        ctx.save(); ctx.translate(cx + sgn*w*0.13, h*0.33); ctx.scale(w*0.055, h*0.055); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    ctx.save(); ctx.translate(cx, h*0.47 + sway*h*0.01); ctx.scale(w*0.075, h*0.075); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    # blush
    ctx.set_source_rgba(*C('#9fb1f0', 0.55))
    for sgn in (-1, 1):
        ctx.save(); ctx.translate(cx + sgn*w*0.235, h*0.385); ctx.scale(w*0.05, h*0.028); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()

@sprite("spr_ghost0", 104, 122)
def _(ctx, w, h): ghost_draw(ctx, w, h, 1)

@sprite("spr_ghost1", 104, 122)
def _(ctx, w, h): ghost_draw(ctx, w, h, -1)

# ---------------------------------------------------------------- tombstones

def stone_base(ctx, w, h, path_fn, seed):
    g = lin_grad(0, 0, w*0.2, h, [(0, C('#9aa0af')), (0.5, C('#767d8c')), (1, C('#4d525e'))])
    ctx.set_source(g); path_fn(); ctx.fill_preserve()
    ctx.set_source_rgba(*C('#23262e')); ctx.set_line_width(3); ctx.stroke()
    # cracks
    rnd = random.Random(seed)
    ctx.set_source_rgba(*C('#3a3e48', 0.9)); ctx.set_line_width(1.6)
    for _ in range(2):
        x, y = w*(0.25 + rnd.random()*0.5), h*(0.15 + rnd.random()*0.3)
        ctx.move_to(x, y)
        for _ in range(4):
            x += (rnd.random()-0.5)*w*0.22; y += h*0.12*rnd.random()
            ctx.line_to(x, y)
        ctx.stroke()
    # moss at base
    ctx.set_source_rgba(*C('#4a6b3a', 0.85))
    for i in range(4):
        mx = w*(0.12 + 0.25*i + rnd.random()*0.08)
        ctx.save(); ctx.translate(mx, h*0.97); ctx.scale(w*0.10, h*0.05)
        ctx.arc(0, 0, 1, math.pi, 2*math.pi); ctx.restore(); ctx.fill()

@sprite("spr_grave0", 96, 122)
def _(ctx, w, h):
    def path():
        ctx.move_to(w*0.08, h)
        ctx.line_to(w*0.08, h*0.34)
        ctx.arc(w*0.5, h*0.34, w*0.42, math.pi, 2*math.pi)
        ctx.line_to(w*0.92, h)
        ctx.close_path()
    stone_base(ctx, w, h, path, 11)
    ctx.select_font_face("Copperplate", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(w*0.30)
    ext = ctx.text_extents("RIP")
    ctx.set_source_rgba(*C('#31353e'))
    ctx.move_to(w/2 - ext.width/2, h*0.44)
    ctx.show_text("RIP")

@sprite("spr_grave1", 96, 122)
def _(ctx, w, h):  # celtic-ish cross
    def path():
        aw = w*0.16
        ctx.move_to(w*0.5-aw, h); ctx.line_to(w*0.5-aw, h*0.42)
        ctx.line_to(w*0.10, h*0.42); ctx.line_to(w*0.10, h*0.26)
        ctx.line_to(w*0.5-aw, h*0.26); ctx.line_to(w*0.5-aw, h*0.06)
        ctx.line_to(w*0.5+aw, h*0.06); ctx.line_to(w*0.5+aw, h*0.26)
        ctx.line_to(w*0.90, h*0.26); ctx.line_to(w*0.90, h*0.42)
        ctx.line_to(w*0.5+aw, h*0.42); ctx.line_to(w*0.5+aw, h)
        ctx.close_path()
    stone_base(ctx, w, h, path, 22)

@sprite("spr_grave2", 96, 122)
def _(ctx, w, h):  # gothic pointed slab
    def path():
        ctx.move_to(w*0.10, h)
        ctx.line_to(w*0.10, h*0.38)
        ctx.curve_to(w*0.10, h*0.10, w*0.5, h*0.02, w*0.5, h*0.02)
        ctx.curve_to(w*0.5, h*0.02, w*0.90, h*0.10, w*0.90, h*0.38)
        ctx.line_to(w*0.90, h)
        ctx.close_path()
    stone_base(ctx, w, h, path, 33)
    ctx.select_font_face("Copperplate", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(w*0.22)
    ext = ctx.text_extents("BOO")
    ctx.set_source_rgba(*C('#31353e'))
    ctx.move_to(w/2 - ext.width/2, h*0.52)
    ctx.show_text("BOO")

# ---------------------------------------------------------------- cauldron

def cauldron_draw(ctx, w, h, frame):
    cx = w/2
    pot_top = h*0.30
    pot = rad_grad(cx - w*0.15, pot_top + h*0.18, w*0.62, [
        (0, C('#4a4f5e')), (0.55, C('#2b2f3a')), (1, C('#14161d'))])
    # legs
    ctx.set_source_rgba(*C('#14161d'))
    for sgn in (-1, 1):
        ctx.save(); ctx.translate(cx + sgn*w*0.26, h*0.94); ctx.rotate(sgn*0.25)
        ctx.scale(w*0.045, h*0.09); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    # body
    ctx.set_source(pot)
    ctx.save(); ctx.translate(cx, pot_top + h*0.30); ctx.scale(w*0.44, h*0.335)
    ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill_preserve()
    ctx.set_source_rgba(*C('#0a0b10')); ctx.set_line_width(3); ctx.stroke()
    # rim
    ctx.set_source(pot)
    ctx.save(); ctx.translate(cx, pot_top); ctx.scale(w*0.47, h*0.085)
    ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill_preserve()
    ctx.set_source_rgba(*C('#0a0b10')); ctx.set_line_width(3); ctx.stroke()
    # brew surface
    brew = rad_grad(cx, pot_top, w*0.42, [(0, C('#b7ff66')), (0.5, C('#59e04e')), (1, C('#1f9e30'))])
    ctx.set_source(brew)
    ctx.save(); ctx.translate(cx, pot_top); ctx.scale(w*0.40, h*0.062)
    ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    # bubbles
    rnd = random.Random(3 + frame)
    for i in range(6):
        bx = cx + (rnd.random()-0.5) * w*0.62
        by = pot_top + (rnd.random()-0.5) * h*0.06 - (h*0.05 if rnd.random() > 0.5 else 0)
        r = w*(0.018 + rnd.random()*0.03)
        ctx.set_source_rgba(*C('#ccff8a', 0.95))
        ctx.arc(bx, by, r, 0, 2*math.pi); ctx.fill()
        ctx.set_source_rgba(*C('#2c8f2c')); ctx.set_line_width(1.4)
        ctx.arc(bx, by, r, 0, 2*math.pi); ctx.stroke()
    # drip on side
    ctx.set_source_rgba(*C('#4ecb45'))
    dx = cx - w*0.30 if frame == 0 else cx + w*0.27
    ctx.move_to(dx - 3, pot_top + h*0.05)
    ctx.curve_to(dx - 4, pot_top + h*0.16, dx - 5, pot_top + h*0.20, dx, pot_top + h*0.235)
    ctx.curve_to(dx + 5, pot_top + h*0.20, dx + 4, pot_top + h*0.16, dx + 3, pot_top + h*0.05)
    ctx.close_path(); ctx.fill()
    # highlight
    ctx.set_source_rgba(1, 1, 1, 0.12)
    ctx.save(); ctx.translate(cx - w*0.22, pot_top + h*0.24); ctx.rotate(0.35)
    ctx.scale(w*0.09, h*0.16); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()

@sprite("spr_cauldron0", 172, 132)
def _(ctx, w, h): cauldron_draw(ctx, w, h, 0)

@sprite("spr_cauldron1", 172, 132)
def _(ctx, w, h): cauldron_draw(ctx, w, h, 1)

# ---------------------------------------------------------------- moon

@sprite("spr_moon", 200, 200)
def _(ctx, w, h):
    cx, cy, r = w/2, h/2, w*0.47
    g = rad_grad(cx - r*0.3, cy - r*0.35, r*1.7, [
        (0, C('#fdf6d8')), (0.6, C('#f0e5b2')), (0.92, C('#cfc084')), (1, C('#b3a469'))])
    ctx.set_source(g); ctx.arc(cx, cy, r, 0, 2*math.pi); ctx.fill()
    craters = [(-0.35, -0.25, 0.16), (0.22, -0.42, 0.10), (0.38, 0.10, 0.20),
               (-0.12, 0.34, 0.12), (-0.48, 0.28, 0.08), (0.05, -0.05, 0.07)]
    for ox, oy, cr in craters:
        px, py, pr = cx + ox*r, cy + oy*r, cr*r
        if math.hypot(ox, oy) + cr > 0.96: continue
        cg = rad_grad(px - pr*0.3, py - pr*0.4, pr*1.9, [(0, C('#c9ba85')), (1, C('#e6dbae'))])
        ctx.set_source(cg); ctx.arc(px, py, pr, 0, 2*math.pi); ctx.fill()
        ctx.set_source_rgba(*C('#a8996a', 0.8)); ctx.set_line_width(1.8)
        ctx.arc(px, py, pr, math.pi*0.6, math.pi*1.7); ctx.stroke()

# ---------------------------------------------------------------- clouds (A8)

for ci in range(2):
    @sprite(f"spr_cloud{ci}", 250, 84, "a8")
    def _(ctx, w, h, ci=ci):
        rnd = random.Random(60 + ci * 7)
        lobes = 8
        for i in range(lobes):
            t = i / (lobes - 1)
            lx = w*0.10 + t * w*0.80
            ly = h*0.55 - math.sin(t * math.pi) * h*0.22 + (rnd.random()-0.5)*h*0.1
            lr = (h*0.30 + rnd.random()*h*0.16) * (0.6 + 0.6*math.sin(t*math.pi))
            g = rad_grad(lx, ly, lr*1.15, [(0, (1,1,1,0.75)), (0.6, (1,1,1,0.45)), (1, (1,1,1,0.0))])
            ctx.set_source(g); ctx.arc(lx, ly, lr*1.15, 0, 2*math.pi); ctx.fill()

# ---------------------------------------------------------------- dirt mound

@sprite("spr_mound", 196, 92)
def _(ctx, w, h):
    cx, cy = w/2, h*0.56
    rx, ry = w*0.48, h*0.40
    g = lin_grad(0, cy - ry, 0, cy + ry, [
        (0, C('#7a4a2c')), (0.45, C('#6b3f24')), (1, C('#3e2415'))])
    ctx.set_source(g)
    ctx.save(); ctx.translate(cx, cy); ctx.scale(rx, ry)
    ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    # crest highlight
    ctx.set_source_rgba(*C('#96613a', 0.85))
    ctx.save(); ctx.translate(cx, cy - ry*0.36); ctx.scale(rx*0.78, ry*0.34)
    ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    # clods
    rnd = random.Random(71)
    for i in range(16):
        a = rnd.random()*2*math.pi
        rr = math.sqrt(rnd.random())
        x = cx + math.cos(a)*rx*0.86*rr
        y = cy + math.sin(a)*ry*0.80*rr
        s = 3 + rnd.random()*6
        ctx.set_source_rgba(*C('#a06b3f' if rnd.random() > 0.45 else '#4a2c1a', 0.8))
        ctx.save(); ctx.translate(x, y); ctx.scale(s, s*0.62)
        ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    # grass tufts on the rim
    ctx.set_source_rgba(*C('#3f6b33'))
    ctx.set_line_width(2.2)
    for i in range(9):
        bx = cx + (i - 4) * rx * 0.21 + (rnd.random()-0.5)*8
        by = cy + ry*0.92 - abs(i-4)*3
        for k in (-1, 0, 1):
            ctx.move_to(bx, by)
            ctx.curve_to(bx + k*4, by - 6, bx + k*7, by - 9, bx + k*9, by - 13)
            ctx.stroke()

# ---------------------------------------------------------------- glows (A8)

for gname, gsz, gpow in (("spr_glow_s", 160, 2.2), ("spr_glow_l", 300, 2.6)):
    @sprite(gname, gsz, gsz, "a8")
    def _(ctx, w, h, gpow=gpow):
        cx, cy, r = w/2, h/2, w/2
        g = cairo.RadialGradient(cx, cy, 0, cx, cy, r)
        for i in range(13):
            t = i / 12
            g.add_color_stop_rgba(t, 0, 0, 0, (1.0 - t) ** gpow)
        ctx.set_source(g)
        ctx.arc(cx, cy, r, 0, 2*math.pi)
        ctx.fill()

# ---------------------------------------------------------------- witch silhouette (A8)

def witch_draw(ctx, w, h, frame):
    ctx.set_source_rgba(0, 0, 0, 1)
    # broom stick
    ctx.set_line_width(h*0.055)
    ctx.move_to(w*0.04, h*0.72); ctx.line_to(w*0.78, h*0.55); ctx.stroke()
    # bristles
    ctx.set_line_width(h*0.028)
    rnd = random.Random(8 + frame)
    for i in range(7):
        ctx.move_to(w*0.10 + rnd.random()*w*0.03, h*0.70 + (rnd.random()-0.5)*h*0.06)
        ctx.line_to(w*0.005, h*0.62 + i*h*0.045 + (rnd.random()-0.5)*h*0.03)
        ctx.stroke()
    # body seated
    ctx.save(); ctx.translate(w*0.47, h*0.47); ctx.rotate(-0.12)
    ctx.scale(w*0.105, h*0.24); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    # legs
    ctx.set_line_width(h*0.06)
    ctx.move_to(w*0.47, h*0.62); ctx.curve_to(w*0.56, h*0.74, w*0.62, h*0.72, w*0.66, h*0.64); ctx.stroke()
    # cape flowing behind
    fl = h*0.10 if frame == 0 else -h*0.06
    ctx.move_to(w*0.44, h*0.36)
    ctx.curve_to(w*0.30, h*0.42, w*0.20, h*0.52 + fl, w*0.09, h*0.44 + fl*1.6)
    ctx.curve_to(w*0.22, h*0.62 + fl, w*0.34, h*0.64, w*0.45, h*0.60)
    ctx.close_path(); ctx.fill()
    # head + chin + nose
    ctx.arc(w*0.545, h*0.28, h*0.085, 0, 2*math.pi); ctx.fill()
    ctx.move_to(w*0.60, h*0.30); ctx.line_to(w*0.665, h*0.315); ctx.line_to(w*0.60, h*0.345)
    ctx.close_path(); ctx.fill()
    # hat
    ctx.move_to(w*0.46, h*0.235)
    ctx.line_to(w*0.665, h*0.215)   # brim
    ctx.line_to(w*0.60, h*0.20)
    ctx.line_to(w*0.575, h*0.02)    # tip
    ctx.line_to(w*0.52, h*0.21)
    ctx.close_path(); ctx.fill()
    ctx.set_line_width(h*0.035)
    ctx.move_to(w*0.44, h*0.24); ctx.line_to(w*0.685, h*0.215); ctx.stroke()

@sprite("spr_witch0", 150, 82, "a8")
def _(ctx, w, h): witch_draw(ctx, w, h, 0)

@sprite("spr_witch1", 150, 82, "a8")
def _(ctx, w, h): witch_draw(ctx, w, h, 1)

# ---------------------------------------------------------------- dead tree (A8)

@sprite("spr_tree", 230, 270, "a8")
def _(ctx, w, h):
    ctx.set_source_rgba(0, 0, 0, 1)
    rnd = random.Random(13)
    def branch(x, y, ang, ln, wd, depth):
        if depth == 0 or ln < 6:
            return
        x2 = x + math.cos(ang) * ln
        y2 = y - math.sin(ang) * ln
        ctx.set_line_width(max(1.6, wd))
        mx = (x+x2)/2 + (rnd.random()-0.5)*ln*0.5
        my = (y+y2)/2 - rnd.random()*ln*0.2
        ctx.move_to(x, y); ctx.curve_to(mx, my, mx, my, x2, y2); ctx.stroke()
        n = 2 if depth > 2 else 2
        for i in range(n):
            na = ang + (rnd.random()-0.5) * 1.5
            branch(x2, y2, na, ln * (0.6 + rnd.random()*0.15), wd*0.55, depth-1)
    # trunk
    ctx.set_line_width(w*0.10)
    ctx.move_to(w*0.5, h)
    ctx.curve_to(w*0.47, h*0.75, w*0.53, h*0.62, w*0.50, h*0.52)
    ctx.stroke()
    branch(w*0.50, h*0.54, math.pi/2 + 0.15, h*0.16, w*0.075, 5)
    branch(w*0.50, h*0.60, math.pi/2 + 0.9, h*0.14, w*0.06, 4)
    branch(w*0.50, h*0.58, math.pi/2 - 0.8, h*0.15, w*0.06, 4)

# ---------------------------------------------------------------- candies

@sprite("spr_candycorn", 46, 52)
def _(ctx, w, h):
    ctx.save()
    ctx.translate(w/2, h/2); ctx.rotate(0.18); ctx.translate(-w/2, -h/2)
    def cone():
        ctx.move_to(w*0.5, h*0.04)
        ctx.curve_to(w*0.72, h*0.30, w*0.92, h*0.78, w*0.88, h*0.86)
        ctx.curve_to(w*0.80, h*0.98, w*0.20, h*0.98, w*0.12, h*0.86)
        ctx.curve_to(w*0.08, h*0.78, w*0.28, h*0.30, w*0.5, h*0.04)
        ctx.close_path()
    cone(); ctx.clip()
    ctx.set_source_rgba(*C('#fff6e8')); ctx.paint()
    ctx.set_source_rgba(*C('#ff9d1f')); ctx.rectangle(0, h*0.34, w, h*0.36); ctx.fill()
    ctx.set_source_rgba(*C('#ffd23f')); ctx.rectangle(0, h*0.70, w, h*0.30); ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.35)
    ctx.save(); ctx.translate(w*0.36, h*0.42); ctx.rotate(-0.25); ctx.scale(w*0.07, h*0.28)
    ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    ctx.reset_clip(); ctx.restore()
    ctx.save(); ctx.translate(w/2, h/2); ctx.rotate(0.18); ctx.translate(-w/2, -h/2)
    cone(); ctx.set_source_rgba(*C('#8a5a1a')); ctx.set_line_width(2.4); ctx.stroke()
    ctx.restore()

@sprite("spr_candywrap", 54, 40)
def _(ctx, w, h):
    cx, cy = w/2, h/2
    g = rad_grad(cx - 5, cy - 5, w*0.35, [(0, C('#c77dff')), (0.7, C('#9333ea')), (1, C('#6b21a8'))])
    for sgn in (-1, 1):  # wrapper ends
        ctx.set_source(g)
        ctx.move_to(cx + sgn*w*0.24, cy - 2*sgn)
        ctx.line_to(cx + sgn*w*0.47, cy - h*0.32)
        ctx.line_to(cx + sgn*w*0.42, cy)
        ctx.line_to(cx + sgn*w*0.47, cy + h*0.32)
        ctx.close_path(); ctx.fill_preserve()
        ctx.set_source_rgba(*C('#3b0764')); ctx.set_line_width(2); ctx.stroke()
    ctx.set_source(g)
    ctx.save(); ctx.translate(cx, cy); ctx.scale(w*0.26, h*0.40); ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore()
    ctx.fill_preserve()
    ctx.set_source_rgba(*C('#3b0764')); ctx.set_line_width(2.2); ctx.stroke()
    ctx.set_source_rgba(*C('#f0abfc', 0.9)); ctx.set_line_width(2.6)
    for off in (-0.5, 0.35):
        ctx.save(); ctx.translate(cx, cy); ctx.scale(w*0.26, h*0.40)
        ctx.move_to(off, -0.85); ctx.curve_to(off+0.25, -0.3, off+0.25, 0.3, off, 0.85)
        ctx.restore(); ctx.stroke()
    ctx.set_source_rgba(1, 1, 1, 0.5)
    ctx.save(); ctx.translate(cx - w*0.08, cy - h*0.16); ctx.rotate(-0.4); ctx.scale(w*0.09, h*0.05)
    ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()

@sprite("spr_eyeball", 44, 44)
def _(ctx, w, h):
    cx, cy, r = w/2, h/2, w*0.46
    g = rad_grad(cx - r*0.3, cy - r*0.35, r*1.6, [(0, C('#ffffff')), (0.75, C('#f2ede4')), (1, C('#c9bfae'))])
    ctx.set_source(g); ctx.arc(cx, cy, r, 0, 2*math.pi); ctx.fill_preserve()
    ctx.set_source_rgba(*C('#8a8070')); ctx.set_line_width(1.8); ctx.stroke()
    rnd = random.Random(21)  # veins
    ctx.set_source_rgba(*C('#c0392b', 0.8)); ctx.set_line_width(1.3)
    for i in range(5):
        a = rnd.random()*2*math.pi
        x0, y0 = cx + math.cos(a)*r*0.95, cy + math.sin(a)*r*0.95
        x1, y1 = cx + math.cos(a)*r*0.45, cy + math.sin(a)*r*0.45
        ctx.move_to(x0, y0)
        ctx.curve_to((x0+x1)/2 + 3, (y0+y1)/2 - 3, (x0+x1)/2 - 2, (y0+y1)/2 + 2, x1, y1)
        ctx.stroke()
    ig = rad_grad(cx - 2, cy - 2, r*0.42, [(0, C('#84e05a')), (0.7, C('#2e9e3a')), (1, C('#186327'))])
    ctx.set_source(ig); ctx.arc(cx, cy, r*0.40, 0, 2*math.pi); ctx.fill()
    ctx.set_source_rgba(*C('#0d0f0a')); ctx.arc(cx, cy, r*0.185, 0, 2*math.pi); ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.9); ctx.arc(cx - r*0.14, cy - r*0.16, r*0.08, 0, 2*math.pi); ctx.fill()

@sprite("spr_skull", 46, 50)
def _(ctx, w, h):
    cx = w/2
    g = rad_grad(cx - w*0.15, h*0.28, w*0.75, [(0, C('#ffffff')), (0.7, C('#e8e2d0')), (1, C('#b8b09a'))])
    ctx.set_source(g)
    ctx.arc(cx, h*0.40, w*0.42, 0, 2*math.pi); ctx.fill()  # cranium
    ctx.set_source(g)
    ctx.rectangle(cx - w*0.24, h*0.58, w*0.48, h*0.30); ctx.fill()  # jaw block
    ctx.set_source_rgba(*C('#6e675a')); ctx.set_line_width(2)
    ctx.arc(cx, h*0.40, w*0.42, math.pi*0.15, math.pi*0.85); ctx.stroke()
    # eyes
    ctx.set_source_rgba(*C('#14120c'))
    for sgn in (-1, 1):
        ctx.save(); ctx.translate(cx + sgn*w*0.17, h*0.40); ctx.scale(w*0.115, h*0.10)
        ctx.arc(0, 0, 1, 0, 2*math.pi); ctx.restore(); ctx.fill()
    # nose
    ctx.move_to(cx, h*0.48); ctx.line_to(cx - w*0.05, h*0.585); ctx.line_to(cx + w*0.05, h*0.585)
    ctx.close_path(); ctx.fill()
    # teeth
    ctx.set_source_rgba(*C('#57503f')); ctx.set_line_width(1.6)
    for i in range(-2, 3):
        ctx.move_to(cx + i*w*0.09, h*0.70); ctx.line_to(cx + i*w*0.09, h*0.86); ctx.stroke()
    ctx.move_to(cx - w*0.24, h*0.70); ctx.line_to(cx + w*0.24, h*0.70); ctx.stroke()

# ---------------------------------------------------------------- title art (A8, tinted at runtime)

def wobble_text(ctx, text, font, size, weight=cairo.FONT_WEIGHT_BOLD, jitter=0.05, ybase=0.72):
    """Per-letter rotation/baseline wobble; fills current surface, returns width used."""
    ctx.select_font_face(font, cairo.FONT_SLANT_NORMAL, weight)
    ctx.set_font_size(size)
    rnd = random.Random(666)
    x = 6
    surf_h = ctx.get_target().get_height() / SS
    for i, ch in enumerate(text):
        ext = ctx.text_extents(ch)
        ang = (rnd.random() - 0.5) * 2 * jitter
        dy = (rnd.random() - 0.5) * size * 0.07
        ctx.save()
        ctx.translate(x + ext.x_advance/2, surf_h * ybase + dy)
        ctx.rotate(ang)
        ctx.move_to(-ext.x_advance/2, 0)
        ctx.set_source_rgba(0, 0, 0, 1)
        ctx.text_path(ch)
        ctx.fill_preserve()
        ctx.set_line_width(size * 0.045)  # fatten
        ctx.stroke()
        ctx.restore()
        x += ext.x_advance * 1.02
    return x

@sprite("spr_title", 400, 78, "a8")
def _(ctx, w, h):
    wobble_text(ctx, "HALLOWEEN", "Luminari", h * 0.80, jitter=0.06, ybase=0.70)
    # slime drips: a few, thick, teardrop-ended, uneven
    rnd = random.Random(35)
    ctx.set_source_rgba(0, 0, 0, 1)
    for fx in (0.115, 0.27, 0.455, 0.63, 0.80, 0.92):
        dx = w * (fx + (rnd.random() - 0.5) * 0.02)
        dl = h * (0.12 + rnd.random() * 0.24)
        dw = 5.0 + rnd.random() * 3.0
        y0 = h * 0.72
        ctx.move_to(dx - dw/2, y0)
        ctx.curve_to(dx - dw/2, y0 + dl*0.6, dx - dw*0.30, y0 + dl*0.85, dx - dw*0.30, y0 + dl)
        ctx.arc(dx, y0 + dl, dw*0.30, math.pi, 2*math.pi)  # bulb (flipped arc dir below)
        ctx.curve_to(dx + dw*0.30, y0 + dl*0.85, dx + dw/2, y0 + dl*0.6, dx + dw/2, y0)
        ctx.close_path(); ctx.fill()
        ctx.arc(dx, y0 + dl, dw*0.52, 0, 2*math.pi); ctx.fill()

@sprite("spr_title_sub", 210, 40, "a8")
def _(ctx, w, h):
    wobble_text(ctx, "ARCADE", "Herculanum", h * 0.72, jitter=0.03, ybase=0.74)

# ---------------------------------------------------------------- menu icons

@sprite("spr_ico_pumpkin", 88, 78)
def _(ctx, w, h):
    ctx.scale(88/132, 78/116); pumpkin_body(ctx, 132, 116, 1)

@sprite("spr_ico_bat", 88, 60)
def _(ctx, w, h):
    ctx.scale(88/100, 60/68); bat_draw(ctx, 100, 68, 0)

@sprite("spr_ico_cauldron", 104, 80)
def _(ctx, w, h):
    ctx.scale(104/172, 80/132); cauldron_draw(ctx, 172, 132, 0)

# ---------------------------------------------------------------- bitmap fonts (A8 glyphs)

FONTS = []  # (cname, dict)

def build_font(cname, family, size, weight=cairo.FONT_WEIGHT_BOLD):
    surf, mctx = make_ctx(int(size*3), int(size*3))
    mctx.select_font_face(family, cairo.FONT_SLANT_NORMAL, weight)
    mctx.set_font_size(size)
    fe = mctx.font_extents()  # ascent, descent, height, ...
    glyphs = {}
    for code in range(32, 91):
        ch = chr(code)
        ext = mctx.text_extents(ch)
        adv = ext.x_advance
        if ch == ' ' or ext.width == 0:
            glyphs[code] = dict(pw=0, ph=0, ox=0, oy=0, adv=round(adv), data=None)
            continue
        gw = int(math.ceil(ext.width)) + 4
        gh = int(math.ceil(ext.height)) + 4
        gs, gctx = make_ctx(gw, gh)
        gctx.select_font_face(family, cairo.FONT_SLANT_NORMAL, weight)
        gctx.set_font_size(size)
        gctx.set_source_rgba(0, 0, 0, 1)
        gctx.move_to(2 - ext.x_bearing, 2 - ext.y_bearing)
        gctx.show_text(ch)
        rgba = surf_to_rgba(downsample(gs, gw, gh))
        a8 = rgba_to_a8_portrait(rgba)
        glyphs[code] = dict(pw=gh, ph=gw,
                            ox=round(ext.x_bearing) - 2, oy=round(ext.y_bearing) - 2,
                            adv=round(adv), data=a8)
    FONTS.append((cname, dict(ascent=round(fe[0]), lineh=round(fe[2]), glyphs=glyphs)))

build_font("font_hud", "Arial Rounded MT Bold", 30)
build_font("font_big", "Herculanum", 48)
build_font("font_small", "Arial Rounded MT Bold", 20)

# ---------------------------------------------------------------- emit C

def fmt_arr16(a):
    return ",".join(str(int(v)) for v in a.flatten())

def fmt_arr8(a):
    return ",".join(str(int(v)) for v in a.flatten())

hdr = []
hdr.append("// AUTO-GENERATED by tools/gen_assets.py — do not edit.")
hdr.append("#pragma once")
hdr.append("#include <stdint.h>")
hdr.append("enum SprFmt : uint8_t { FMT_ARGB4444 = 0, FMT_A8 = 1, FMT_RGB565 = 2 };")
hdr.append("struct Sprite { uint16_t pw, ph; uint16_t lw, lh; uint8_t fmt; const void* data; };")
hdr.append("struct Glyph { uint8_t pw, ph; int8_t ox, oy; uint8_t adv; const uint8_t* data; };")
hdr.append("struct BFont { uint8_t ascent, lineh; const Glyph* glyphs; }; // chars 32..90")
src = ["// AUTO-GENERATED by tools/gen_assets.py — do not edit.", '#include "assets.h"']

total = 0
for name, fmt, arr, lw, lh in SPRITES:
    cfmt = {"argb4444": "FMT_ARGB4444", "a8": "FMT_A8", "rgb565": "FMT_RGB565"}[fmt]
    ctype = "uint8_t" if fmt == "a8" else "uint16_t"
    pw, ph = arr.shape[1], arr.shape[0]
    body = fmt_arr8(arr) if fmt == "a8" else fmt_arr16(arr)
    src.append(f"static const {ctype} {name}_px[] = {{{body}}};")
    src.append(f"const Sprite {name} = {{{pw},{ph},{lw},{lh},{cfmt},{name}_px}};")
    hdr.append(f"extern const Sprite {name};")
    total += arr.size * (1 if fmt == "a8" else 2)

for cname, f in FONTS:
    glyph_rows = []
    for code in range(32, 91):
        g = f["glyphs"][code]
        if g["data"] is not None:
            src.append(f"static const uint8_t {cname}_g{code}[] = {{{fmt_arr8(g['data'])}}};")
            total += g["data"].size
            dref = f"{cname}_g{code}"
        else:
            dref = "nullptr"
        glyph_rows.append(f"{{{g['pw']},{g['ph']},{g['ox']},{g['oy']},{g['adv']},{dref}}}")
    src.append(f"static const Glyph {cname}_glyphs[59] = {{{','.join(glyph_rows)}}};")
    src.append(f"const BFont {cname} = {{{f['ascent']},{f['lineh']},{cname}_glyphs}};")
    hdr.append(f"extern const BFont {cname};")

with open(os.path.join(SRC, "assets.h"), "w") as fh:
    fh.write("\n".join(hdr) + "\n")
with open(os.path.join(SRC, "assets_data.cpp"), "w") as fh:
    fh.write("\n".join(src) + "\n")

print(f"sprites: {len(SPRITES)}, fonts: {len(FONTS)}, data bytes: {total} ({total/1024:.0f} KB)")

# ---------------------------------------------------------------- preview sheet

cols = 6
cell = 190
rows = (len(SPRITES) + cols - 1) // cols
sheet = cairo.ImageSurface(cairo.FORMAT_ARGB32, cols * cell, rows * cell + 30)
sc = cairo.Context(sheet)
sc.set_source_rgb(0.09, 0.05, 0.14); sc.paint()
for i in range(0, cols * cell, 20):  # checkers
    for j in range(0, rows * cell, 20):
        if (i // 20 + j // 20) % 2 == 0:
            sc.set_source_rgba(1, 1, 1, 0.03); sc.rectangle(i, j, 20, 20); sc.fill()
sc.select_font_face("Menlo", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
for idx, (name, fmt, arr, lw, lh) in enumerate(SPRITES):
    gx, gy = (idx % cols) * cell, (idx // cols) * cell
    png = cairo.ImageSurface.create_from_png(os.path.join(PREV, name + ".png"))
    s = min(1.0, (cell - 30) / max(png.get_width(), png.get_height()))
    sc.save()
    sc.translate(gx + (cell - png.get_width() * s) / 2, gy + 6 + (cell - 30 - png.get_height() * s) / 2)
    sc.scale(s, s)
    if fmt == "a8":  # show alpha sprites tinted purple so they're visible
        sc.push_group()
        sc.set_source_surface(png, 0, 0); sc.paint()
        mask = sc.pop_group()
        sc.set_source_rgb(0.65, 0.5, 1.0)
        sc.mask(mask)
    else:
        sc.set_source_surface(png, 0, 0); sc.paint()
    sc.restore()
    sc.set_source_rgb(0.7, 0.7, 0.8); sc.set_font_size(11)
    sc.move_to(gx + 8, gy + cell - 6); sc.show_text(f"{name} {lw}x{lh} {fmt}")
sheet.write_to_png(os.path.join(PREV, "_sheet.png"))
print("preview:", os.path.join(PREV, "_sheet.png"))

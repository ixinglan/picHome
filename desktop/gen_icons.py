#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 PicHome 桌面端 App 图标（纯标准库，无第三方依赖）。

设计目标：有层次、不像「平涂蓝块」。
  - 背景：indigo → blue 竖向渐变 + 顶部柔光，营造空间感；
  - 主体：白色「相片卡片」带柔和投影与细描边，立体感更强；
  - 卡片内：暖色太阳（金→橙渐变）+ 前后两层山峦（浅蓝 / 深蓝），
            一眼看出是「图床 / 相册」的意象。

输出：desktop/src-tauri/icons/icon.png (1024)
  -> 交给 `node_modules/.bin/tauri icon` 套 macOS 圆角遮罩、生成整套
     icon.icns / 各尺寸 PNG / android / ios 资源。
  （菜单栏托盘已移除，不再生成 menubar.png）
"""
import struct
import zlib
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "src-tauri", "icons")
os.makedirs(OUT_DIR, exist_ok=True)


def encode_png(w, h, rgba):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * w * 4:(y + 1) * w * 4]
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def write_png(path, w, h, rgba):
    with open(path, "wb") as f:
        f.write(encode_png(w, h, rgba))


def make_buf(w, h):
    return bytearray(w * h * 4)


def setpx(buf, w, h, x, y, r, g, b, a=255):
    if 0 <= x < w and 0 <= y < h:
        i = (y * w + x) * 4
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b
        buf[i + 3] = a


def blend(buf, w, h, x, y, r, g, b, a):
    """alpha 合成：src over dst。"""
    if 0 <= x < w and 0 <= y < h and a > 0:
        i = (y * w + x) * 4
        sa = a / 255.0
        da = buf[i + 3] / 255.0
        out_a = sa + da * (1 - sa)
        if out_a <= 0:
            return
        nr = (r * sa + buf[i] * (da * (1 - sa))) / out_a
        ng = (g * sa + buf[i + 1] * (da * (1 - sa))) / out_a
        nb = (b * sa + buf[i + 2] * (da * (1 - sa))) / out_a
        buf[i] = int(nr + 0.5)
        buf[i + 1] = int(ng + 0.5)
        buf[i + 2] = int(nb + 0.5)
        buf[i + 3] = int(out_a * 255 + 0.5)


def lerp(a, b, t):
    return int(a + (b - a) * t)


def rrect_inside(cx, cy, hw, hh, r):
    """圆角矩形内的判定闭包。"""
    def inside(x, y):
        if x < cx - hw or x > cx + hw or y < cy - hh or y > cy + hh:
            return False
        if x < cx - hw + r and y < cy - hh + r:
            return (x - (cx - hw + r)) ** 2 + (y - (cy - hh + r)) ** 2 <= r * r
        if x > cx + hw - r and y < cy - hh + r:
            return (x - (cx + hw - r)) ** 2 + (y - (cy - hh + r)) ** 2 <= r * r
        if x < cx - hw + r and y > cy + hh - r:
            return (x - (cx - hw + r)) ** 2 + (y - (cy + hh - r)) ** 2 <= r * r
        if x > cx + hw - r and y > cy + hh - r:
            return (x - (cx + hw - r)) ** 2 + (y - (cy + hh - r)) ** 2 <= r * r
        return True
    return inside


def mountain(buf, w, h, apex, left, right, color, base_y, clip):
    """填充一座山（三角形），底边贴卡片底部，裁剪在卡片内。"""
    ax, ay = apex
    lx, ly = left
    rx, ry = right
    minx = int(min(ax, lx, rx)) - 2
    maxx = int(max(ax, lx, rx)) + 2
    miny = int(min(ay, ly, ry)) - 2
    maxy = int(max(ay, ly, ry)) + 2

    def x_on(p1, p2, yy):
        if p2[1] == p1[1]:
            return p1[0]
        t = (yy - p1[1]) / (p2[1] - p1[1])
        return p1[0] + t * (p2[0] - p1[0])

    for y in range(miny, maxy + 1):
        if y < 0 or y >= h:
            continue
        xl = x_on((ax, ay), (lx, ly), y)
        xr = x_on((ax, ay), (rx, ry), y)
        x0 = int(min(xl, xr))
        x1 = int(max(xl, xr))
        for x in range(x0, x1 + 1):
            if clip(x, y):
                setpx(buf, w, h, x, y, color[0], color[1], color[2])


# ============================ 1) 画布 / 背景 ============================
W = 1024
buf = make_buf(W, W)

# indigo -> blue 竖向渐变 + 顶部柔光
top = (79, 70, 229)      # #4F46E5
bot = (37, 99, 235)      # #2563EB
glow_cx, glow_cy = W // 2, int(W * 0.30)
glow_r = W * 0.62
glow_r2 = glow_r * glow_r
for y in range(W):
    t = y / (W - 1)
    br = lerp(top[0], bot[0], t)
    bg = lerp(top[1], bot[1], t)
    bb = lerp(top[2], bot[2], t)
    dy = y - glow_cy
    for x in range(W):
        dx = x - glow_cx
        d2 = dx * dx + dy * dy
        ga = max(0.0, 1 - (d2 / glow_r2) ** 0.5) * 0.5
        r = min(255, br + (255 - br) * ga)
        g = min(255, bg + (255 - bg) * ga)
        b = min(255, bb + (255 - bb) * ga)
        setpx(buf, W, W, x, y, int(r), int(g), int(b))

# ============================ 2) 相片卡片 ============================
cw = int(W * 0.56)
ch = int(W * 0.44)
card_cx = W // 2
card_cy = int(W * 0.55)
card_r = int(W * 0.055)
card_in = rrect_inside(card_cx, card_cy, cw / 2, ch / 2, card_r)

# 卡片投影（向下偏移，半透明深色）
sh_in = rrect_inside(card_cx, card_cy + 16, cw / 2, ch / 2, card_r)
for y in range(int(card_cy - ch / 2 - 20), int(card_cy + ch / 2 + 40)):
    for x in range(int(card_cx - cw / 2 - 20), int(card_cx + cw / 2 + 20)):
        if sh_in(x, y):
            blend(buf, W, W, x, y, 8, 15, 35, 70)

# 卡片填充（白 -> 浅灰蓝渐变）
c_top = (255, 255, 255)
c_bot = (223, 230, 242)
cy0 = int(card_cy - ch / 2)
cy1 = int(card_cy + ch / 2)
for y in range(cy0, cy1 + 1):
    t = (y - cy0) / ch
    for x in range(int(card_cx - cw / 2), int(card_cx + cw / 2) + 1):
        if card_in(x, y):
            setpx(buf, W, W, x, y,
                  lerp(c_top[0], c_bot[0], t),
                  lerp(c_top[1], c_bot[1], t),
                  lerp(c_top[2], c_bot[2], t))

# 卡片细描边（内侧 3px）
bw = 3
for y in range(cy0, cy1 + 1):
    for x in range(int(card_cx - cw / 2), int(card_cx + cw / 2) + 1):
        if not card_in(x, y):
            continue
        dmin = min(y - cy0, cy1 - y, x - int(card_cx - cw / 2), int(card_cx + cw / 2) - x)
        if dmin < bw:
            blend(buf, W, W, x, y, 15, 23, 42, 60)

# ============================ 3) 山峦（先画，太阳压在上层）============================
base = cy1  # 卡片底边
mountain(buf, W, W, (546, 536), (226, base), (798, base), (167, 199, 255), base, card_in)   # 后山：浅蓝
mountain(buf, W, W, (432, 581), (214, base), (684, base), (54, 99, 196), base, card_in)    # 前山：深蓝

# ============================ 4) 太阳（金 -> 橙渐变，柔边）============================
sun_r = cw * 0.15
sun_cx = card_cx - cw * 0.27
sun_cy = card_cy - ch * 0.22
s_top = (255, 222, 128)
s_bot = (255, 165, 70)
for y in range(int(sun_cy - sun_r) - 2, int(sun_cy + sun_r) + 3):
    for x in range(int(sun_cx - sun_r) - 2, int(sun_cx + sun_r) + 3):
        if not card_in(x, y):
            continue
        dx = x - sun_cx
        dy = y - sun_cy
        dd = ((dx * dx + dy * dy) ** 0.5) / sun_r
        if dd <= 1.0:
            t = max(0.0, min(1.0, dd))
            a = 255 if dd < 0.9 else int(255 * (1 - (dd - 0.9) / 0.1))
            blend(buf, W, W, x, y,
                  lerp(s_top[0], s_bot[0], t),
                  lerp(s_top[1], s_bot[1], t),
                  lerp(s_top[2], s_bot[2], t), a)

# ============================ 输出 ============================
write_png(os.path.join(OUT_DIR, "icon.png"), W, W, buf)
size = os.path.getsize(os.path.join(OUT_DIR, "icon.png"))
print("icon.png written, bytes =", size)
print("OUT_DIR =", OUT_DIR)

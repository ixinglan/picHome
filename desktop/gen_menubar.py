#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 macOS 菜单栏（顶部状态栏）托盘图标 menubar.png。

设计要点（针对用户反馈「蓝色方块太丑」）：
- macOS 菜单栏图标应当是「单色 + 透明底」的 template 图，
  系统会按当前主题（浅色/深色）自动着色，从而自然融入菜单栏，
  而不是一块刺眼的实心彩色方块。
- 造型与 App 图标同源：山峦 + 太阳 的剪影，辨识度高、有设计感。
- 用纯黑（#000）绘制，实际颜色由系统接管，这里只关心 alpha 形状。
- 画布 256x256，导出为 PNG（Tauri 用 include_bytes! 直接加载）。

依赖：Pillow
用法：python3 gen_menubar.py
"""

from PIL import Image, ImageDraw

S = 256  # 画布尺寸（正方形）


def main():
    # 透明画布
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 太阳：右上角实心圆（菜单栏图标里作为点缀，山峦之上）
    sun_center = (176, 84)
    sun_r = 30
    d.ellipse(
        [sun_center[0] - sun_r, sun_center[1] - sun_r,
         sun_center[0] + sun_r, sun_center[1] + sun_r],
        fill=(0, 0, 0, 255),
    )

    # 山峦：两层叠加的三角形剪影（前浅后深靠位置错落表现层次）
    # 后山（稍高、略偏左）
    d.polygon(
        [(18, 212), (96, 116), (150, 168), (150, 212)],
        fill=(0, 0, 0, 255),
    )
    # 前山（稍矮、偏右，与后山交错形成山脊线）
    d.polygon(
        [(120, 212), (198, 104), (238, 212)],
        fill=(0, 0, 0, 255),
    )

    out = "src-tauri/icons/menubar.png"
    img.save(out)
    print(f"[ok] 已生成菜单栏图标: {out} ({img.size})")


if __name__ == "__main__":
    main()

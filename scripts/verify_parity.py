#!/usr/bin/env python3
"""
verify_parity.py — Đối chiếu file .pptx THẬT với preview web (SlidePreview.tsx)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Sandbox này không cài được LibreOffice (apt bị chặn), nên script này dựng 2
renderer độc lập từ 2 phía của hợp đồng:

  [PPTX]      đọc thẳng cây XML của file .pptx do generator_service sinh
              (<a:gradFill>, <a:alpha> 3-6%, xfrm, rPr, biến thể card...).
  [PREVIEW]   tái hiện đúng luật render của SlidePreview.tsx từ cùng một
              PresentationResponse JSON (background CSS gradient string,
              variant accent_top/accent_left/outline/cta, icon, opacity).

Xuất ảnh so sánh cạnh nhau từng slide -> verification/compare_*.png.
Emoji ngoài plane BMP (🪐 📈 ...) được thay bằng glyph đơn sắc tương đương
theo theme vì sandbox không có font color-emoji; file PPTX thật giữ nguyên
emoji (PowerPoint/Segoe UI Emoji hiển thị đủ).
"""

from __future__ import annotations

import io
import math
import os
import re
import sys

import numpy as np
from lxml import etree
from PIL import Image, ImageDraw, ImageFont

BACKEND_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "exoticmorph-backend")
sys.path.insert(0, BACKEND_ROOT)

from app.schemas.slide_schema import GenerateRequest, LLMOutput  # noqa: E402
from app.services.layout_engine import compute_layout  # noqa: E402
from app.services.generator_service import build_pptx_from_schema  # noqa: E402
from app.services.visual_themes import parse_gradient_css  # noqa: E402

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
EMU_IN = 914400.0

DPI = 120
SLIDE_W_IN, SLIDE_H_IN = 13.333, 7.5
W, H = int(SLIDE_W_IN * DPI), int(SLIDE_H_IN * DPI)

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
F_REG = os.path.join(FONT_DIR, "DejaVuSans.ttf")
F_BOLD = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")

# Thay thế emoji ngoài BMP (font DejaVu không có) bằng glyph đơn sắc theo theme.
EMOJI_FALLBACK = {
    "🪐": "☄", "🌌": "✧", "🛰": "◈", "⭐": "★", "🌍": "◉", "🌱": "✿", "🌿": "✿",
    "🍃": "❧", "🌊": "≈", "📈": "▲", "📉": "▼", "📊": "▤", "💰": "$", "🏦": "▦",
    "💹": "▲", "🩺": "⚕", "🧬": "ฑ", "💊": "●", "🫀": "♥", "🔋": "▮", "🌬": "≈",
    "🔥": "✷", "🤖": "⚙", "🧠": "◉", "💻": "▬", "🎓": "◆", "📚": "▤", "🧪": "⚗",
    "📐": "△", "🔬": "◄", "🏛": "▦", "📜": "▫", "🗺": "▣", "⚱": "⚱", "🏺": "◮",
    "🍜": "◕", "🌾": "❧", "🍳": "◉", "🥕": "▲", "🍲": "◉",
}


def sub_emoji(text: str) -> str:
    return "".join(EMOJI_FALLBACK.get(ch, ch) for ch in text)


def font(size_px: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(F_BOLD if bold else F_REG, max(6, int(round(size_px))))


def hex_rgb(h: str):
    h = (h or "").lstrip("#")
    if len(h) != 6:
        h = "0A0C12"
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def rgba(color, alpha: float):
    return (int(color[0]), int(color[1]), int(color[2]), int(round(255 * max(0.0, min(1.0, alpha)))))


def lerp_color(c1, c2, t: float):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def draw_linear_gradient(img: Image.Image, box, stops, dir_deg: float) -> None:
    """Vẽ linear gradient phủ hình chữ nhật `box` theo hướng (độ, quy 0=sang phải)."""
    x0, y0, x1, y1 = box
    rad = math.radians(dir_deg)
    dx, dy = math.cos(rad), math.sin(rad)
    wd, hd = x1 - x0, y1 - y0
    length = abs(wd * dx) + abs(hd * dy)
    if length <= 0:
        return
    xs = np.arange(wd)
    ys = np.arange(hd)
    px, py = np.meshgrid(xs, ys)
    proj = ((px - wd / 2) * dx + (py - hd / 2) * dy + length / 2) / length
    t = np.clip(proj, 0.0, 1.0) * 100.0  # vị trí stops tính theo %
    positions = [p for p, _ in stops]
    colors = [hex_rgb(c) for _, c in stops]
    r = np.interp(t, positions, [c[0] for c in colors])
    g = np.interp(t, positions, [c[1] for c in colors])
    b = np.interp(t, positions, [c[2] for c in colors])
    rgb = np.stack([r, g, b], axis=-1).astype(np.uint8)
    grad = Image.fromarray(rgb, "RGB")
    img.paste(grad, (int(x0), int(y0)))


def rounded_rect(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrap_text(text: str, f, max_w: float) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        cand = f"{cur} {w_}".strip()
        if f.getlength(cand) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines or [""]


def draw_text_block(
    img, box, runs_per_line, f_size, align="l", anchor="t", line_h=1.18,
    color=(255, 255, 255), bold=False, spacing_em=0.0, clip=True,
):
    """Vẽ các dòng chữ trong box. runs_per_line: list[list[(text,color,bold)]] đã wrap."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    line_px = f_size * line_h
    total_h = len(runs_per_line) * line_px
    cy = y0 if anchor != "ctr" else y0 + max(0, (y1 - y0 - total_h) / 2)
    for line_runs in runs_per_line:
        spacing = f_size * spacing_em
        line_w = sum(
            font(f_size, b).getlength(t) + spacing * len(t) for t, _, b in line_runs
        )
        cx = x0
        if align == "ctr":
            cx = x0 + (x1 - x0 - line_w) / 2
        elif align == "r":
            cx = x1 - line_w
        for t, col, is_bold in line_runs:
            f = font(f_size, is_bold)
            d.text((cx, cy), t, font=f, fill=rgba(col, 1.0))
            cx += f.getlength(t) + spacing * len(t)
        cy += line_px
        if clip and cy > y1 + line_px:
            break


# ═════════════════════════════════════════════════════════════════════════════
# [PPTX] RENDERER — đọc thẳng XML của file .pptx
# ═════════════════════════════════════════════════════════════════════════════

def _fill_info(spPr) -> tuple[str, object]:
    """Trả về ('none'|'solid'(color,alpha)|'grad'(stops,ang), ...)."""
    if spPr is None:
        return "none", None
    nofill = spPr.find(f"{{{A_NS}}}noFill")
    if nofill is not None:
        return "none", None
    grad = spPr.find(f"{{{A_NS}}}gradFill")
    if grad is not None:
        stops = []
        for gs in grad.findall(f"{{{A_NS}}}gsLst/{{{A_NS}}}gs"):
            pos = int(gs.get("pos")) / 1000.0
            clr = gs.find(f"{{{A_NS}}}srgbClr")
            alpha = 1.0
            if clr is not None:
                a = clr.find(f"{{{A_NS}}}alpha")
                if a is not None:
                    alpha = int(a.get("val")) / 100000.0
            stops.append((pos, "#" + (clr.get("val") if clr is not None else "0A0C12"), alpha))
        lin = grad.find(f"{{{A_NS}}}lin")
        ang = int(lin.get("ang")) / 60000.0 if lin is not None else 0.0
        return "grad", (stops, ang)
    solid = spPr.find(f"{{{A_NS}}}solidFill")
    if solid is not None:
        clr = solid.find(f"{{{A_NS}}}srgbClr")
        if clr is not None:
            alpha = 1.0
            a = clr.find(f"{{{A_NS}}}alpha")
            if a is not None:
                alpha = int(a.get("val")) / 100000.0
            return "solid", ("#" + clr.get("val"), alpha)
    return "none", None


def _line_info(spPr):
    if spPr is None:
        return None
    ln = spPr.find(f"{{{A_NS}}}ln")
    if ln is None:
        return None
    kind, payload = _fill_info(ln)
    if kind != "solid":
        return None
    color, alpha = payload
    w_emu = int(ln.get("w") or "9525")
    return (color, alpha, w_emu / EMU_IN * DPI)


def _para_props(p_el):
    pPr = p_el.find(f"{{{A_NS}}}pPr")
    align = (pPr.get("algn") if pPr is not None else None) or "l"
    defRPr = pPr.find(f"{{{A_NS}}}defRPr") if pPr is not None else None
    spcBef = 0.0
    if pPr is not None:
        pts = pPr.find(f"{{{A_NS}}}spcBef/{{{A_NS}}}spcPts")
        if pts is not None:
            spcBef = int(pts.get("val")) / 100.0
    line_h = 1.18
    if pPr is not None:
        pct = pPr.find(f"{{{A_NS}}}lnSpc/{{{A_NS}}}spcPct")
        if pct is not None:
            line_h = int(pct.get("val")) / 100000.0
    return align, defRPr, spcBef, line_h


def _run_props(r_el, defRPr):
    rPr = r_el.find(f"{{{A_NS}}}rPr")
    def _get(node, tag):
        return node.find(f"{{{A_NS}}}{tag}") if node is not None else None

    def prop(which, cast):
        for node in (rPr, defRPr):
            v = node.get(which) if node is not None else None
            if v is not None:
                return cast(v)
        return None

    sz = prop("sz", lambda v: int(v) / 100.0) or 12.0
    bold = prop("b", lambda v: v == "1") or False
    clr = None
    for node in (rPr, defRPr):
        srgb = _get(node, "solidFill")
        if srgb is not None:
            c = srgb.find(f"{{{A_NS}}}srgbClr")
            if c is not None:
                clr = hex_rgb("#" + c.get("val"))
                break
    spacing_pt = prop("spc", lambda v: int(v) / 100.0) or 0.0
    return sz, bold, (clr or (255, 255, 255)), spacing_pt


def render_pptx_slide(prs_slide) -> Image.Image:
    img = Image.new("RGB", (W, H), (10, 12, 18))
    sld = prs_slide._element

    # 1) Background
    bg = sld.find(f"{{{P_NS}}}cSld/{{{P_NS}}}bg")
    if bg is not None:
        bgPr = bg.find(f"{{{P_NS}}}bgPr")
        kind, payload = _fill_info(bgPr)
        if kind == "grad":
            stops, ang = payload
            stops = [(p, c) for p, c, _ in stops]
            draw_linear_gradient(img, (0, 0, W, H), stops, ang)
        elif kind == "solid":
            color, _ = payload
            ImageDraw.Draw(img).rectangle((0, 0, W, H), fill=hex_rgb(color))

    d = ImageDraw.Draw(img, "RGBA")
    spTree = sld.find(f"{{{P_NS}}}cSld/{{{P_NS}}}spTree")

    for sp in spTree.findall(f"{{{P_NS}}}sp"):
        spPr = sp.find(f"{{{P_NS}}}spPr")
        xfrm = spPr.find(f"{{{A_NS}}}xfrm") if spPr is not None else None
        if xfrm is None:
            continue
        off = xfrm.find(f"{{{A_NS}}}off")
        ext = xfrm.find(f"{{{A_NS}}}ext")
        x0 = int(off.get("x")) / EMU_IN * DPI
        y0 = int(off.get("y")) / EMU_IN * DPI
        x1 = x0 + int(ext.get("cx")) / EMU_IN * DPI
        y1 = y0 + int(ext.get("cy")) / EMU_IN * DPI
        geom = spPr.find(f"{{{A_NS}}}prstGeom")
        prst = geom.get("prst") if geom is not None else "rect"

        kind, payload = _fill_info(spPr)
        line = _line_info(spPr)

        if prst == "roundRect":
            radius = 0.16667 * min(x1 - x0, y1 - y0)
            if kind == "solid":
                color, alpha = payload
                rounded_rect(d, (x0, y0, x1, y1), radius, fill=rgba(hex_rgb(color), alpha))
            elif kind == "grad":
                stops, ang = payload
                tmp = Image.new("RGBA", (int(x1 - x0) + 1, int(y1 - y0) + 1), (0, 0, 0, 0))
                draw_linear_gradient(tmp, (0, 0, x1 - x0, y1 - y0), [(p, c) for p, c, _ in stops], ang)
                mask = Image.new("L", tmp.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, tmp.size[0] - 1, tmp.size[1] - 1), radius=radius, fill=255)
                img.paste(tmp.convert("RGB"), (int(x0), int(y0)), mask)
            elif kind == "none":
                rounded_rect(d, (x0, y0, x1, y1), radius, fill=None)
            if line:
                color, alpha, wpx = line
                rounded_rect(d, (x0, y0, x1, y1), radius, outline=rgba(hex_rgb(color), alpha), width=max(1, int(wpx)))
        else:  # rect / ellipse
            shape_box = (x0, y0, x1, y1)
            fill = None
            if kind == "solid":
                color, alpha = payload
                fill = rgba(hex_rgb(color), alpha)
            if prst == "ellipse":
                d.ellipse(shape_box, fill=fill)
            else:
                d.rectangle(shape_box, fill=fill)

        # Text
        txBody = sp.find(f"{{{P_NS}}}txBody")
        if txBody is None:
            continue
        bodyPr = txBody.find(f"{{{A_NS}}}bodyPr")
        anchor = bodyPr.get("anchor") if bodyPr is not None else None
        lIns = int(bodyPr.get("lIns", 91440)) / EMU_IN * DPI if bodyPr is not None else 0.1 * DPI
        rIns = int(bodyPr.get("rIns", 91440)) / EMU_IN * DPI if bodyPr is not None else 0.1 * DPI
        tIns = int(bodyPr.get("tIns", 45720)) / EMU_IN * DPI if bodyPr is not None else 0.05 * DPI
        wrap = (bodyPr.get("wrap") if bodyPr is not None else "square") != "none"

        inner = (x0 + lIns, y0 + tIns, x1 - rIns, y1)
        cy = inner[1]
        for p_el in txBody.findall(f"{{{A_NS}}}p"):
            align, defRPr, spcBef, line_h = _para_props(p_el)
            runs = [
                (r.find(f"{{{A_NS}}}t").text or "", *_run_props(r, defRPr))
                for r in p_el.findall(f"{{{A_NS}}}r")
                if r.find(f"{{{A_NS}}}t") is not None
            ]
            if not runs:
                cy += 12 * 1.18
                continue
            f_size = max(r[1] for r in runs) * DPI / 72.0
            bold = any(r[2] for r in runs)
            cy += spcBef * DPI / 72.0
            text_full = sub_emoji("".join(r[0] for r in runs))
            max_w = inner[2] - inner[0]
            if wrap:
                lines = wrap_text(text_full, font(f_size, bold), max_w)
                para_runs = [[(ln, runs[0][3] if runs else (255, 255, 255), bold)] for ln in lines]
            else:
                para_runs = [[(text_full, runs[0][3], bold)]]
            total_h = len(para_runs) * f_size * line_h
            draw_y = cy if anchor != "ctr" else cy + max(0, ((y1 - tIns) - cy - total_h) / 2)
            spacing_em = (runs[0][4] / 72.0 * DPI) / f_size if runs else 0.0
            draw_text_block(
                img, (inner[0], draw_y, inner[2], y1), para_runs, f_size,
                align=align, anchor=anchor if anchor else "t", line_h=line_h,
                spacing_em=spacing_em,
            )
            cy += total_h
    return img


# ═════════════════════════════════════════════════════════════════════════════
# [PREVIEW] RENDERER — tái hiện luật render của SlidePreview.tsx từ JSON
# ═════════════════════════════════════════════════════════════════════════════

def hex_to_rgba_ts(hex_str, alpha):
    if not hex_str:
        return rgba((255, 255, 255), alpha)
    h = hex_str.strip().replace("#", "")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        return rgba((255, 255, 255), alpha)
    return rgba(hex_rgb("#" + h), alpha)


def body_font_size(title_size: float) -> float:
    if title_size >= 40: return 11.5
    if title_size >= 24: return 12.5
    if title_size >= 18: return 11.2
    if title_size >= 15: return 10.4
    if title_size >= 13: return 9.8
    return 9.2


def render_preview_slide(slide_json) -> Image.Image:
    img = Image.new("RGB", (W, H), (10, 12, 18))
    d = ImageDraw.Draw(img, "RGBA")

    bg = (slide_json.get("bg_color") or "").strip()
    grad = parse_gradient_css(bg) if bg.startswith("linear-gradient") else None
    if grad:
        angle_css, stops = grad
        draw_linear_gradient(img, (0, 0, W, H), stops, angle_css - 90.0)
    else:
        d.rectangle((0, 0, W, H), fill=hex_rgb(bg or "#0A0C12"))

    def pt_px(pt): return max(6, pt / 72.0 * DPI)
    def in_px(v): return v * DPI
    palette_sub = (154, 163, 181)

    for e in slide_json["elements"]:
        x0 = e["x"] / 100.0 * W
        y0 = e["y"] / 100.0 * H
        x1 = x0 + e["width"] / 100.0 * W
        y1 = y0 + e["height"] / 100.0 * H
        font_pt = e.get("font_size") or (9 if e["type"] == "footer" else 12)
        t = e["type"]

        if t == "decoration":
            alpha = e.get("opacity") or 1.0
            if e.get("shape_type") == "oval":
                d.ellipse((x0, y0, x1, y1), fill=hex_to_rgba_ts(e.get("bg_color"), alpha))
            else:
                d.rectangle((x0, y0, x1, y1), fill=hex_to_rgba_ts(e.get("bg_color"), alpha))
            continue

        if t in ("accent", "connector"):
            color = e.get("bg_color") or e.get("accent_color") or "#8B5CF6"
            if e.get("shape_type") == "oval":
                d.ellipse((x0, y0, x1, y1), fill=hex_to_rgba_ts(color, 1.0))
            else:
                d.rectangle((x0, y0, x1, y1), fill=hex_to_rgba_ts(color, 1.0))
            continue

        if t == "badge":
            color = e.get("bg_color") or "#7C3AED"
            radius = (min(x1 - x0, y1 - y0) / 2) if e.get("shape_type") == "oval" else in_px(0.14)
            rounded_rect(d, (x0, y0, x1, y1), radius, fill=hex_to_rgba_ts(color, 1.0))
            runs = [[(sub_emoji(e["content"]), hex_rgb(e.get("text_color") or "#FFFFFF"), True)]]
            draw_text_block(img, (x0, y0, x1, y1), runs, pt_px(font_pt), align="ctr", anchor="ctr")
            continue

        if t in ("heading", "kicker", "footer"):
            color = hex_rgb(e.get("text_color") or "#F6F8FB")
            align = {"right": "r", "center": "ctr"}.get(e.get("align") or "left", "l")
            spacing = 0.22 if t == "kicker" else (0.01 if t == "footer" else 0.0)
            text = sub_emoji(e["content"].upper() if t == "kicker" else e["content"])
            f = font(pt_px(font_pt), True)
            lines = [text] if t == "footer" else wrap_text(text, f, x1 - x0)
            runs = [[(ln, color, True)] for ln in lines]
            line_h = 1.04 if (t == "heading" and font_pt >= 40) else 1.12
            draw_text_block(img, (x0, y0, x1, y1), runs, pt_px(font_pt), align=align, spacing_em=spacing, line_h=line_h)
            continue

        # ---- card / metric / text / shape ----
        variant = e.get("variant") or "accent_top"
        is_stat = (e.get("font_size") or 0) >= 40
        is_cta = e.get("align") == "center" and not e.get("sub_text")
        is_outline = variant == "outline"
        border = (
            hex_to_rgba_ts(e.get("accent_color") or "#10B981", 0.5)
            if is_outline
            else (hex_to_rgba_ts(e.get("border_color"), 0.55) if e.get("border_color") else None)
        )
        radius = in_px(0.14)
        fill = None if is_outline else hex_to_rgba_ts(e.get("bg_color") or "#141827", 1.0)
        rounded_rect(d, (x0, y0, x1, y1), radius, fill=fill, outline=border,
                     width=max(1, int(pt_px(0.75))))

        if variant == "accent_top" and not is_cta:
            aw = x1 - x0
            d.rounded_rectangle(
                (x0 + 0.08 / 13.333 * W, y0 + in_px(0.045), x0 + 0.08 / 13.333 * W + aw - 0.16 / 13.333 * W,
                 y0 + in_px(0.045) + in_px(0.045)),
                radius=999, fill=hex_to_rgba_ts(e.get("accent_color") or "#10B981", 1.0))
        if variant == "accent_left" and not is_cta:
            d.rounded_rectangle(
                (x0 + in_px(0.02), y0 + in_px(0.1), x0 + in_px(0.02) + in_px(0.062), y1 - in_px(0.1)),
                radius=999, fill=hex_to_rgba_ts(e.get("accent_color") or "#10B981", 1.0))

        title_color = hex_rgb(e.get("text_color") or "#F6F8FB")
        accent_color = hex_rgb(e.get("accent_color") or "#10B981")
        icon = sub_emoji(e["icon"]) if e.get("icon") else ""

        if is_stat:
            if icon:
                d.text((x1 - in_px(0.16) - pt_px(16), y0 + in_px(0.16)), icon,
                       font=font(pt_px(16), False), fill=rgba(accent_color, 0.92))
            ew, eh = (x1 - x0) / DPI, (y1 - y0) / DPI
            stat_title_h = min(1.14, max(0.72, eh * 0.34))
            stat_title_y = 0.54 if eh >= 2.2 else 0.20
            runs = [[(e["content"], title_color, True)]]
            draw_text_block(img, (x0 + in_px(0.18), y0 + in_px(stat_title_y), x1 - in_px(0.18),
                                  y0 + in_px(stat_title_y + stat_title_h)),
                            runs, pt_px(font_pt), align="ctr", anchor="ctr", line_h=0.94)
            if e.get("sub_text"):
                body_h = max(0.30, eh - stat_title_h - 0.16 - 0.74)
                body_y = min(eh - body_h - 0.16, stat_title_y + stat_title_h + 0.16)
                f = font(pt_px(body_font_size(font_pt)), False)
                lines = wrap_text(e["sub_text"], f, (x1 - x0) - 2 * in_px(0.18))
                runs = [[(ln, palette_sub, False)] for ln in lines]
                draw_text_block(img, (x0 + in_px(0.18), y0 + in_px(body_y), x1 - in_px(0.18), y1),
                                runs, pt_px(body_font_size(font_pt)), align="ctr", line_h=1.12)
            continue

        pad_l = in_px(0.18) + (in_px(0.062) + in_px(0.08) if variant == "accent_left" else 0)
        pad_y0 = in_px(0.08) if is_cta else in_px(0.20)
        pad_y1 = in_px(0.08) if is_cta else in_px(0.16)
        box = (x0 + pad_l, y0 + pad_y0, x1 - in_px(0.18), y1 - pad_y1)
        f_t = font(pt_px(font_pt), True)
        title_lines = wrap_text(sub_emoji(e["content"]), f_t, box[2] - box[0])
        title_runs = [[(icon + "  " if (i == 0 and icon) else "", accent_color, True),
                       (ln, title_color, True)] for i, ln in enumerate(title_lines)]
        draw_text_block(img, box, title_runs, pt_px(font_pt), align="ctr" if is_cta else "l",
                        anchor="ctr" if is_cta else "t", line_h=1.08)
        if e.get("sub_text") and not is_cta:
            y_after = box[1] + len(title_runs) * pt_px(font_pt) * 1.08 + in_px(0.07)
            f_b = font(pt_px(body_font_size(font_pt)), False)
            lines = wrap_text(e["sub_text"], f_b, box[2] - box[0])
            runs = [[(ln, palette_sub, False)] for ln in lines]
            draw_text_block(img, (box[0], y_after, box[2], box[3]), runs,
                            pt_px(body_font_size(font_pt)), line_h=1.12)
    return img


# ═════════════════════════════════════════════════════════════════════════════
# MAIN — dựng deck, build PPTX, render 2 phía, ghép ảnh so sánh
# ═════════════════════════════════════════════════════════════════════════════

DESC = ("Khí quyển Kim Tinh dày 92 bar với 96.5% CO2 tạo hiệu ứng nhà kính mất kiểm soát, "
        "giữ nhiệt độ bề mặt ở 465 độ C cả ngày lẫn đêm.")


def _card(i, title, desc, color="#8B5CF6"):
    return {"morph_id": f"card_{i}", "title": title, "description": desc, "color_theme": color, "order": i}


def space_payload():
    return {
        "topic": "Nghịch lý nhiệt Kim Tinh",
        "visual_theme": "space",
        "slides": [
            {"slide_number": 1, "section": "CÂU HỎI MỞ ĐẦU",
             "slide_title": "Vì sao Kim Tinh nóng 465 °C dù xa Mặt Trời hơn Thuỷ Tinh?",
             "layout_type": "COVER_HERO",
             "cards": [_card(0, "Một nghịch lý nhiệt động giữa hai hành tinh láng giềng", DESC),
                       _card(1, "KHÍ QUYỂN", "Lớp vỏ khí 92 bar.", "#10B981"),
                       _card(2, "QUỸ ĐẠO", "Chu kỳ 225 ngày gần tròn nhất hệ.", "#06B6D4")]},
            {"slide_number": 2, "section": "SỐ LIỆU",
             "slide_title": "Áp suất bề mặt Kim Tinh gấp 92 lần Trái Đất",
             "layout_type": "BIG_STAT_CALLOUT",
             "cards": [_card(0, "92 bar", "Tương đương độ sâu 900 m dưới đại dương Trái Đất."),
                       _card(1, "CO2 chiếm 96.5%", "Khí nhà kính chính, mây H2SO4 phản xạ 75% ánh sáng.", "#10B981")]},
            {"slide_number": 3, "section": "CƠ CHẾ",
             "slide_title": "Ba tầng khí quyển vận hành như một nồi áp suất",
             "layout_type": "ASYMMETRIC_GRID",
             "cards": [_card(0, "Tầng đối lưu dày 65 km giữ trọn nhiệt lượng", DESC),
                       _card(1, "Mây axit sunfuric", "Phản xạ ánh sáng nhưng bẫy bức xạ hồng ngoại.", "#10B981"),
                       _card(2, "Hiệu ứng nhà kính", "CO2 và SO2 tạo vòng phản hồi không đảo ngược.", "#06B6D4")]},
            {"slide_number": 4, "section": "TIẾN TRÌNH",
             "slide_title": "Bốn giai đoạn hình thành nghịch lý nhiệt",
             "layout_type": "TIMELINE_STEPS",
             "cards": [_card(0, "Giai đoạn 1: đại dương bốc hơi", "Hơi nước bổ sung vào khí quyển nguyên thuỷ."),
                       _card(1, "Giai đoạn 2: CO2 tích tụ", "Núi lửa giải phóng CO2 không bị phong hoá hấp thụ.", "#10B981"),
                       _card(2, "Giai đoạn 3: mất nước", "UV phân ly H2O, hydro thoát ra không gian.", "#06B6D4"),
                       _card(3, "Giai đoạn 4: cân bằng 465 °C", "Khí quyển đạt trạng thái siêu tới hạn ổn định.", "#EC4899")]},
            {"slide_number": 5, "section": "KẾT LUẬN",
             "slide_title": "Kim Tinh là lời cảnh báo cho Trái Đất",
             "layout_type": "CONCLUSION_SUMMARY",
             "cards": [_card(0, "Khoảng cách không quyết định nhiệt độ", "Thành phần khí quyển mới là biến số chi phối."),
                       _card(1, "Hiệu ứng nhà kính có điểm không quay lại", "Vượt ngưỡng bốc hơi đại dương là irreversible.", "#10B981"),
                       _card(2, "Trái Đất đang ở rìa vùng an toàn", "Mô hình khí hậu cho thấy +4 °C kích hoạt vòng phản hồi.", "#06B6D4"),
                       _card(3, "Theo dõi nồng độ CO2 toàn cầu ngay hôm nay", "Giám sát ppm CO2 tại Mauna Loa và cắt giảm phát thải.", "#EC4899")]},
        ],
    }


def finance_payload():
    p = space_payload()
    p["topic"] = "Báo cáo tài chính doanh nghiệp"
    p["visual_theme"] = "finance"
    for s in p["slides"]:
        s["slide_title"] = s["slide_title"].replace("Kim Tinh", "doanh nghiệp").replace("Mặt Trời", "thị trường")
    return p


def build_deck_images(payload, prompt, out_prefix, out_dir):
    raw = LLMOutput.model_validate(payload)
    req = GenerateRequest(prompt=prompt, num_slides=len(payload["slides"]))
    pres = compute_layout(raw, req)
    pres_json = __import__("json").loads(pres.model_dump_json())

    pptx_bytes = build_pptx_from_schema(pres).getvalue()
    from pptx import Presentation as OpenPptx
    prs = OpenPptx(io.BytesIO(pptx_bytes))

    paths = []
    for i, (slide_json, prs_slide) in enumerate(zip(pres_json["slides"], prs.slides), start=1):
        img_pptx = render_pptx_slide(prs_slide)
        img_prev = render_preview_slide(slide_json)
        compare = compose_pair(img_pptx, img_prev, f"{out_prefix} · Slide {i} — {slide_json['layout_type']}")
        path = os.path.join(out_dir, f"compare_{out_prefix}_s{i}.png")
        compare.save(path)
        paths.append(path)
    return paths, pptx_bytes


def compose_pair(left: Image.Image, right: Image.Image, title: str) -> Image.Image:
    pad, header = 24, 56
    canvas = Image.new("RGB", (W * 2 + pad * 3, H + header + pad * 2), (16, 18, 26))
    d = ImageDraw.Draw(canvas)
    f = font(26, True)
    d.text((pad, 14), title, font=f, fill=(240, 244, 250))
    f_lbl = font(20, True)
    d.text((pad, header + 4), "PPTX thật (đọc từ .pptx XML)", font=f_lbl, fill=(120, 220, 180))
    d.text((W + pad * 2, header + 4), "Web preview (logic SlidePreview.tsx)", font=f_lbl, fill=(130, 180, 255))
    canvas.paste(left, (pad, header + pad))
    canvas.paste(right, (W + pad * 2, header + pad))
    return canvas


def contact_sheet(paths, out_path, cols=2):
    from PIL import Image as I
    imgs = [I.open(p) for p in paths]
    w, h = imgs[0].size
    rows = math.ceil(len(imgs) / cols)
    pad = 16
    sheet = Image.new("RGB", (cols * w + (cols + 1) * pad, rows * h + (rows + 1) * pad), (16, 18, 26))
    for i, im in enumerate(imgs):
        r, c = divmod(i, cols)
        sheet.paste(im, (pad + c * (w + pad), pad + r * (h + pad)))
    sheet.save(out_path)
    return out_path


def main():
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "verification")
    os.makedirs(out_dir, exist_ok=True)

    paths_space, pptx_space = build_deck_images(
        space_payload(), "nghịch lý nhiệt Kim Tinh hành tinh", "space", out_dir)
    paths_fin, pptx_fin = build_deck_images(
        finance_payload(), "báo cáo tài chính doanh nghiệp kpi", "finance", out_dir)

    pptx_path = os.path.join(out_dir, "space_theme_deck.pptx")
    with open(pptx_path, "wb") as fh:
        fh.write(pptx_space)
    pptx_path2 = os.path.join(out_dir, "finance_theme_deck.pptx")
    with open(pptx_path2, "wb") as fh:
        fh.write(pptx_fin)

    sheet = contact_sheet(
        paths_space + paths_fin,
        os.path.join(out_dir, "compare_contact_sheet.png"), cols=2)

    print("Đã xuất:")
    for p in paths_space + paths_fin + [sheet, pptx_path, pptx_path2]:
        print("  -", os.path.relpath(p, os.path.join(out_dir, "..")))


if __name__ == "__main__":
    main()

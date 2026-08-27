"""
Visual Themes (Motif Engine) for ExoticMorph
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Bổ sung "bản sắc thị giác theo chủ đề" cho bộ slide — phá vỡ cảm giác 1 template
PowerPoint cố định được nhồi nội dung khác nhau:

1. **ICON/MOTIF THEO NGỮ CẢNH**: mỗi bài trình chiếu được gán MỘT bộ biểu tượng
   (emoji khoa học) liên quan trực tiếp đến chủ đề — thiên văn → 🪐 ☄ 🌌, tài
   chính → 📈 📊 💰 — đặt cạnh kicker và tiêu đề card thay vì chỉ có thanh màu.

2. **HOẠ TIẾT NỀN RẤT MỜ (3–6%)**: slide thân bài không còn là nền đặc thuần
   túý mà rải lưới toạ độ / chấm sao / lattice chấm với opacity 3–6% — đủ tạo
   chiều sâu, không gây rối mắt. Hoạ tiết được sinh DỰNG (seeded) theo
   (theme, slide_number) nên deterministic: PPTX và preview luôn khớp nhau.

3. **GRADIENT THEO VAI TRÒ SLIDE**:
   - Slide mở bài (COVER_HERO)  : gradient tối có điểm nhấn màu chủ đề (dải sáng
     mờ mô phỏng ánh sáng vũ trụ / glow) thay vì màu đặc.
   - Slide kết luận (CONCLUSION): gradient dâng theo màu accent chính của CTA
     để tạo cảm giác cao trào.

   Gradient được biểu diễn bằng chuỗi CSS `linear-gradient(...)` trong
   `Slide.bg_color` — frontend preview dùng trực tiếp làm CSS `background`,
   còn PPTX builder parse chuỗi này thành `<a:gradFill>` OpenXML tương đương.

Nguồn sự thật duy nhất của bộ motif là module này; `layout_engine` quyết định
ĐẶT ở đâu, `generator_service` (PPTX) và `SlidePreview.tsx` (web) quyết định
VẼ ra sao — luôn từ cùng một dữ liệu `SlideElement`.
"""

import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ==============================================================================
# ĐỊNH DẠNG THEME
# ==============================================================================


@dataclass(frozen=True)
class VisualTheme:
    """Một bộ motif thị giác gắn với ngữ cảnh chủ đề.

    - ``kicker_icons``: biểu tượng xoay vòng đặt cạnh nhãn mục (kicker) của từng
      slide — mỗi slide một icon, tạo nhịp thị giác xuyên suốt bộ slide.
    - ``card_icons``: biểu tượng đặt cạnh tiêu đề card (dùng cho các biến thể
      card không có thanh màu phía trên).
    - ``stat_icon``: biểu tượng xu hướng/đơn vị đặt ở góc card số liệu lớn.
    - ``pattern``: hoạ tiết nền rất mờ cho slide thân bài
      (``stars`` | ``grid`` | ``dots``).
    """

    key: str
    label: str
    keywords: Tuple[str, ...] = ()
    kicker_icons: Tuple[str, ...] = ("✦",)
    card_icons: Tuple[str, ...] = ("✦", "◆", "●", "▲")
    stat_icon: str = "✦"
    pattern: str = "stars"


_GENERIC = VisualTheme(
    key="generic",
    label="Chung (motif hình học)",
    kicker_icons=("✦", "◈", "◆", "✧", "●"),
    card_icons=("✦", "◆", "●", "▲", "◈"),
    stat_icon="✦",
    pattern="stars",
)

# Thứ tự khai báo = thứ tự ưu tiên khi scores bằng nhau (cụ thể trước, chung sau).
_THEME_SPECS: List[VisualTheme] = [
    VisualTheme(
        key="space",
        label="Thiên văn & Vũ trụ",
        keywords=(
            "thiên văn", "vũ trụ", "hành tinh", "hệ mặt trời", "mặt trời",
            "ngôi sao", "thiên hà", "quỹ đạo", "sao chổi", "meteor", "trăng",
            "kim tinh", "hoả tinh", "mộc tinh", "thổ tinh", "sao hoả", "sao kim",
            "không gian", "vệ tinh", "astronomy", "planet", "galaxy", "orbit",
            "star", "cosmic", "cosmos", "universe", "telescope", "asteroid",
            "lunar", "interstellar", "space",
        ),
        kicker_icons=("🪐", "☀", "☄", "🌌", "🛰"),
        card_icons=("🪐", "☄", "🌌", "🛰", "⭐"),
        stat_icon="☄",
        pattern="stars",
    ),
    VisualTheme(
        key="finance",
        label="Tài chính & Kinh doanh",
        keywords=(
            "tài chính", "kinh doanh", "doanh thu", "đầu tư", "cổ phiếu",
            "thị trường", "ngân hàng", "tiền tệ", "lạm phát", "lợi nhuận",
            "chi phí", "vốn", "pitch deck", "startup", "gọi vốn", "kpi", "roi",
            "finance", "market", "revenue", "invest", "stock", "banking",
            "money", "crypto", "bitcoin", "economy", "valuation", "cashflow",
        ),
        kicker_icons=("📈", "📊", "💰", "🏦", "💹"),
        card_icons=("📈", "💰", "📊", "🏦", "💹"),
        stat_icon="📈",
        pattern="grid",
    ),
    VisualTheme(
        key="medical",
        label="Y học & Sức khoẻ",
        keywords=(
            "y học", "y tế", "sức khỏe", "sức khoẻ", "bệnh", "lâm sàng",
            "thuốc", "chẩn đoán", "virus", "vaccine", "gene", "adn", "dna",
            "tim mạch", "ung thư", "bệnh nhân", "medical", "health", "clinical",
            "pharma", "diagnosis", "patient", "hospital", "vaccine", "epidemic",
        ),
        kicker_icons=("⚕", "🩺", "🧬", "💊", "🫀"),
        card_icons=("⚕", "🩺", "🧬", "💊", "🫀"),
        stat_icon="🧬",
        pattern="dots",
    ),
    VisualTheme(
        key="energy",
        label="Năng lượng & Điện",
        keywords=(
            "năng lượng", "năng lượng mặt trời", "năng lượng tái tạo", "điện",
            "pin", "gió", "hạt nhân", "dầu khí", "nhiệt điện", "thủy điện",
            "renewable", "solar", "wind", "nuclear", "battery", "electricity",
            "energy", "power grid", "hydrogen", "fuel", "petrol",
        ),
        kicker_icons=("⚡", "🔋", "☀", "🌬", "🔥"),
        card_icons=("⚡", "🔋", "🌬", "☀", "🔥"),
        stat_icon="⚡",
        pattern="grid",
    ),
    VisualTheme(
        key="tech",
        label="Công nghệ & AI",
        keywords=(
            "công nghệ", "trí tuệ nhân tạo", "phần mềm", "lập trình", "dữ liệu",
            "máy học", "cloud", "mạng", "robot", "bảo mật", "blockchain",
            "microservice", "technology", "software", "data", "machine learning",
            "cyber", "api", "platform", "developer", "automation", "digital",
        ),
        kicker_icons=("⚙", "🤖", "🧠", "⚡", "💻"),
        card_icons=("🤖", "🧠", "⚙", "💻", "🛰"),
        stat_icon="⚡",
        pattern="grid",
    ),
    VisualTheme(
        key="nature",
        label="Thiên nhiên & Môi trường",
        keywords=(
            "thiên nhiên", "môi trường", "khí hậu", "sinh học", "động vật",
            "thực vật", "biển", "rừng", "đa dạng sinh học", "sinh thái",
            "nước ngọt", "đại dương", "nature", "climate", "environment",
            "biology", "ecosystem", "ocean", "forest", "animal", "plant",
            "earth", "wildlife", "green",
        ),
        kicker_icons=("🌿", "🌍", "🌱", "🍃", "🌊"),
        card_icons=("🌿", "🌱", "🌊", "🍃", "🌍"),
        stat_icon="🌱",
        pattern="dots",
    ),
    VisualTheme(
        key="history",
        label="Lịch sử & Văn hoá",
        keywords=(
            "lịch sử", "văn hóa", "văn hoá", "cổ đại", "chiến tranh",
            "triều đại", "khảo cổ", "di sản", "văn minh", "museum", "history",
            "ancient", "war", "dynasty", "heritage", "archaeology",
            "civilization", "medieval", "empire",
        ),
        kicker_icons=("🏛", "📜", "🗺", "⚱", "🏺"),
        card_icons=("🏛", "📜", "🗺", "⚱", "🏺"),
        stat_icon="📜",
        pattern="grid",
    ),
    VisualTheme(
        key="food",
        label="Ẩm thực & Dinh dưỡng",
        keywords=(
            "ẩm thực", "món ăn", "nấu ăn", "nấu món", "nấu", "nguyên liệu",
            "dinh dưỡng", "thực phẩm", "nhà hàng", "bếp", "cà phê", "food",
            "cuisine", "cooking", "recipe", "nutrition", "restaurant", "chef",
            "coffee", "gastronomy", "flavor",
        ),
        kicker_icons=("🍜", "🌾", "🍳", "🥕", "🍲"),
        card_icons=("🍜", "🍳", "🌾", "🥕", "🍲"),
        stat_icon="🌾",
        pattern="dots",
    ),
    VisualTheme(
        key="education",
        label="Giáo dục & Khoa học cơ bản",
        keywords=(
            "giáo dục", "học tập", "trường học", "đại học", "nghiên cứu",
            "khoa học", "thí nghiệm", "toán học", "vật lý", "hoá học", "hóa học",
            "đào tạo", "học thuật", "luận văn", "giảng dạy", "education",
            "school", "university", "research", "science", "study", "physics",
            "chemistry", "math", "academic", "student", "learning",
            "experiment", "scholar",
        ),
        kicker_icons=("🎓", "📚", "🧪", "📐", "🔬"),
        card_icons=("🎓", "📚", "🧪", "🔬", "📐"),
        stat_icon="🎓",
        pattern="grid",
    ),
]

VISUAL_THEMES: Dict[str, VisualTheme] = {t.key: t for t in _THEME_SPECS}
VISUAL_THEMES[_GENERIC.key] = _GENERIC

#: Danh sách key LLM được phép trả về ở top-level `visual_theme`.
VISUAL_THEME_KEYS: Tuple[str, ...] = tuple(t.key for t in _THEME_SPECS) + (_GENERIC.key,)


# ==============================================================================
# SUY LUẬN THEME TỪ NGỮ CẢNH
# ==============================================================================

_SHORT_ASCII_KW = re.compile(r"(?<![a-z0-9])(?P<kw>{kw})(?![a-z0-9])")


def _keyword_hit(text: str, keyword: str) -> bool:
    """Kiểm tra keyword xuất hiện trong text (short ASCII từ khoá dùng word-boundary)."""
    if len(keyword) <= 4 and keyword.isascii():
        matcher = re.compile(_SHORT_ASCII_KW.pattern.replace("{kw}", re.escape(keyword)))
        return matcher.search(text) is not None
    return keyword in text


def infer_visual_theme(text: str) -> VisualTheme:
    """Chọn theme theo điểm keyword có trọng số (từ khoá càng dài càng tin cậy).

    Ví dụ: "năng lượng mặt trời" phải thắng "mặt trời" — nhờ trọng số độ dài,
    theme ``energy`` (keyword 18 ký tự) vượt ``space`` (keyword 8 ký tự).
    """
    haystack = f" {(text or '').lower()} "
    best = _GENERIC
    best_score = 0.0
    for theme in _THEME_SPECS:
        score = 0.0
        for kw in theme.keywords:
            if _keyword_hit(haystack, kw):
                score += len(kw) + 4.0  # thưởng mỗi cú hit + trọng số độ dài
        if score > best_score:
            best, best_score = theme, score
    return best


def resolve_visual_theme(
    prompt: str = "",
    topic: str = "",
    llm_hint: Optional[str] = None,
) -> VisualTheme:
    """Nguồn sự thật về theme của một bài trình chiếu.

    Ưu tiên lựa chọn `visual_theme` của LLM (nếu hợp lệ) — LLM hiểu ngữ cảnh chủ
    đề tốt hơn heuristic; ngược lại suy luận từ prompt + topic; đảm bảo LUÔN trả
    được một theme hợp lệ (generic) dù input rỗng.
    """
    hint = (llm_hint or "").strip().lower()
    if hint:
        if hint in VISUAL_THEMES:
            return VISUAL_THEMES[hint]
        for theme in _THEME_SPECS:  # khớp theo label hoặc tiền tố
            if hint in theme.key or hint in theme.label.lower():
                return theme
    return infer_visual_theme(f"{prompt or ''} {topic or ''}")


def kicker_icon_for(theme: VisualTheme, slide_number: int) -> str:
    """Icon đặt cạnh kicker của slide (xoay vòng theo số slide)."""
    icons = theme.kicker_icons or _GENERIC.kicker_icons
    return icons[(max(slide_number, 1) - 1) % len(icons)]


def card_icon_for(theme: VisualTheme, index: int) -> str:
    """Icon đặt cạnh tiêu đề card (theo vị trí card trong slide)."""
    icons = theme.card_icons or _GENERIC.card_icons
    return icons[max(index, 0) % len(icons)]


# ==============================================================================
# HOẠ TIẾT NỀN RẤT MỜ (opacity 3–6%) — deterministic theo (theme, slide)
# ==============================================================================

#: Giới hạn tổng số hoạ tiết mỗi slide để không vượt MAX_ELEMENTS_PER_SLIDE.
MAX_DECORATIONS_PER_SLIDE = 14

DEFAULT_SLIDE_W_IN = 13.333
DEFAULT_SLIDE_H_IN = 7.5


def pattern_decorations(
    theme: VisualTheme,
    slide_number: int,
    slide_w_in: float = DEFAULT_SLIDE_W_IN,
    slide_h_in: float = DEFAULT_SLIDE_H_IN,
) -> List[Dict[str, object]]:
    """Sinh danh sách hoạ tiết nền (toạ độ INCHES) cho slide thân bài.

    Mỗi hoạ tiết là dict ``{shape, x, y, w, h, opacity}`` với
    ``shape ∈ {"oval", "rect"}`` và opacity trong khoảng 0.03–0.06 (rất mờ,
    chỉ tạo chiều sâu). Kết quả deterministic: cùng (theme, slide_number,
    khung hình) luôn cho cùng toạ độ — PPTX và web preview khớp tuyệt đối.
    """
    rng = random.Random(f"exoticmorph::{theme.key}::{slide_number}::{slide_w_in:.3f}")
    out: List[Dict[str, object]] = []
    pattern = theme.pattern if theme.pattern in ("stars", "grid", "dots") else "stars"

    if pattern == "stars":
        # Chấm sao rải rác toàn khung — mật độ cao hơn ở nửa trên (tránh footer).
        count = 12
        for _ in range(count):
            d = round(rng.uniform(0.035, 0.095), 3)
            x = rng.uniform(0.2, max(0.3, slide_w_in - d - 0.2))
            y = rng.uniform(0.15, max(0.3, slide_h_in - d - 0.5))
            out.append({
                "shape": "oval",
                "x": round(x, 3), "y": round(y, 3), "w": d, "h": d,
                "opacity": round(rng.uniform(0.035, 0.06), 3),
            })

    elif pattern == "grid":
        # Lưới toạ độ mảnh (kiểu biểu đồ khoa học / finance): dọc + ngang.
        x = 0.9 + rng.uniform(-0.25, 0.25)
        while x < slide_w_in - 0.45 and len(out) < 6:
            out.append({
                "shape": "rect", "x": round(x, 3), "y": 0.0,
                "w": 0.012, "h": round(slide_h_in, 3), "opacity": 0.032,
            })
            x += rng.uniform(1.05, 1.5)
        y = 0.85 + rng.uniform(-0.2, 0.2)
        while y < slide_h_in - 0.45 and len(out) < MAX_DECORATIONS_PER_SLIDE:
            out.append({
                "shape": "rect", "x": 0.0, "y": round(y, 3),
                "w": round(slide_w_in, 3), "h": 0.012, "opacity": 0.032,
            })
            y += rng.uniform(1.25, 1.7)

    else:  # dots — lattice chấm (kiểu tế bào / hạt giống)
        cols = []
        x = 0.7
        while x < slide_w_in - 0.3:
            cols.append(x)
            x += 0.95
        pts = []
        row = 0
        y = 0.7
        while y < slide_h_in - 0.4:
            stagger = 0.47 if row % 2 else 0.0
            for cx in cols:
                px = cx + stagger
                if px < slide_w_in - 0.25:
                    pts.append((round(px, 3), round(y, 3)))
            y += 0.92
            row += 1
        rng.shuffle(pts)
        for px, py in pts[: min(16, MAX_DECORATIONS_PER_SLIDE)]:
            out.append({
                "shape": "oval", "x": px, "y": py, "w": 0.03, "h": 0.03,
                "opacity": round(rng.uniform(0.035, 0.05), 3),
            })

    return out[:MAX_DECORATIONS_PER_SLIDE]


# ==============================================================================
# GRADIENT THEO VAI TRÒ SLIDE (chuỗi CSS — frontend dùng thẳng, PPTX parse)
# ==============================================================================

def _hex_to_rgb01(hex_str: str) -> Tuple[int, int, int]:
    clean = (hex_str or "").strip().lstrip("#")
    if len(clean) != 6:
        clean = "0A0C12"
    try:
        return (
            int(clean[0:2], 16),
            int(clean[2:4], 16),
            int(clean[4:6], 16),
        )
    except ValueError:
        return (10, 12, 18)


def _rgb01_to_hex(r: int, g: int, b: int) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, round(r))),
        max(0, min(255, round(g))),
        max(0, min(255, round(b))),
    )


def mix_hex(base: str, tint: str, ratio: float) -> str:
    """Trộn 2 màu hex: ratio=0 → base, ratio=1 → tint."""
    ratio = max(0.0, min(1.0, ratio))
    br, bg_, bb = _hex_to_rgb01(base)
    tr, tg, tb = _hex_to_rgb01(tint)
    return _rgb01_to_hex(
        br + (tr - br) * ratio,
        bg_ + (tg - bg_) * ratio,
        bb + (tb - bb) * ratio,
    )


def cover_gradient_css(bg: str, accent: str, accent2: str) -> str:
    """Gradient nền slide MỞ BÀI: tối ở trái → dải sáng mờ màu chủ đề ở phải."""
    mid = mix_hex(bg, accent2, 0.16)
    end = mix_hex(bg, accent, 0.32)
    return f"linear-gradient(118deg, {bg.upper()} 0%, {mid} 55%, {end} 100%)"


def closing_gradient_css(bg: str, accent: str) -> str:
    """Gradient nền slide KẾT BÀI: dâng theo màu accent của CTA (cao trào)."""
    mid = mix_hex(bg, accent, 0.14)
    end = mix_hex(bg, accent, 0.28)
    return f"linear-gradient(160deg, {bg.upper()} 0%, {mid} 60%, {end} 100%)"


# ==============================================================================
# PARSER CHUỖI GRADIENT (PPTX builder + test dùng chung)
# ==============================================================================

_GRADIENT_RE = re.compile(
    r"^\s*linear-gradient\(\s*(?P<angle>[\d.]+)deg\s*,(?P<stops>.+)\)\s*$",
    re.IGNORECASE,
)
_STOP_RE = re.compile(
    r"^\s*#?(?P<hex>[0-9A-Fa-f]{6})\s+(?P<pos>[\d.]+)%\s*$"
)


def parse_gradient_css(css: Optional[str]) -> Optional[Tuple[float, List[Tuple[float, str]]]]:
    """Parse `linear-gradient(118deg, #0A0C12 0%, #1A1030 55%, #241A4F 100%)`.

    Trả về ``(angle_css_deg, [(pos_percent, '#RRGGBB'), ...])`` hoặc None nếu
    chuỗi không phải gradient hợp lệ (gọi rơi về tô màu đặc).
    """
    if not css or not isinstance(css, str):
        return None
    m = _GRADIENT_RE.match(css)
    if not m:
        return None
    angle = float(m.group("angle"))
    stops: List[Tuple[float, str]] = []
    for raw in m.group("stops").split(","):
        sm = _STOP_RE.match(raw)
        if not sm:
            return None
        stops.append((float(sm.group("pos")), f"#{sm.group('hex').upper()}"))
    if len(stops) < 2:
        return None
    stops.sort(key=lambda s: s[0])
    return angle, stops

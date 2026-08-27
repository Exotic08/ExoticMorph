#!/usr/bin/env bash
# compare_libreoffice.sh — đối chiếu file .pptx thật với preview web bằng LibreOffice
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Quy trình đối chiếu đã thiết lập của dự án: render file .pptx do backend sinh
# ra ảnh bằng LibreOffice để肉眼 so với preview web. (Sandbox dựng code không
# cài được LibreOffice qua apt, nên scripts/verify_parity.py dùng renderer độc
# lập đọc thẳng XML .pptx; script này để chạy trên máy có sẵn LibreOffice.)
#
# Cách dùng:
#   ./scripts/compare_libreoffice.sh verification/space_theme_deck.pptx [thư_mục_ra]
#
# Yêu cầu: soffice (libreoffice-impress), pdftoppm (poppler-utils) hoặc ImageMagick.

set -euo pipefail

PPTX="${1:?Cần đường dẫn file .pptx, ví dụ: verification/space_theme_deck.pptx}"
OUT_DIR="${2:-$(dirname "$PPTX")/libreoffice_render}"
mkdir -p "$OUT_DIR"

echo "→ 1/3 Convert PPTX → PDF bằng LibreOffice..."
soffice --headless --convert-to pdf --outdir "$OUT_DIR" "$PPTX" >/dev/null

PDF="$OUT_DIR/$(basename "${PPTX%.pptx}").pdf"
echo "→ 2/3 Raster PDF → PNG (150dpi)..."
if command -v pdftoppm >/dev/null 2>&1; then
  pdftoppm -png -r 150 "$PDF" "$OUT_DIR/slide"
else
  command -v convert >/dev/null 2>&1 || { echo "Cần pdftoppm (poppler-utils) hoặc ImageMagick convert"; exit 1; }
  convert -density 150 "$PDF" "$OUT_DIR/slide-%02d.png"
fi

echo "→ 3/3 Xong. So từng ảnh slide với preview web trong trình duyệt:"
echo "   npm run dev  →  mở http://localhost:3000  →  tạo cùng prompt rồi đối chiếu."
ls -1 "$OUT_DIR"/*.png

"use client";

import React, { useState, useEffect, useRef } from "react";
import { 
  Download, 
  RotateCcw, 
  Play, 
  Pause, 
  ChevronLeft, 
  ChevronRight, 
  Sparkles, 
  FileCheck2, 
  Layers, 
  CheckCircle,
  Sliders
} from "lucide-react";
import { motion } from "framer-motion";
import confetti from "canvas-confetti";
import { BackendSlideElement, SlidePreviewData, SlideItem } from "@/types";
import { downloadBlob } from "@/lib/download";

interface SlidePreviewProps {
  data: SlidePreviewData;
  cachedBlob?: Blob | null;
  downloadFilename?: string;
  onReset: () => void;
  onEditPrompt: () => void;
  onDownloadRequest?: () => Promise<void>;
  /** Báo lỗi tải file lên trang cha để hiển thị ErrorNotification thân thiện
   *  (thay cho alert() của bản cũ — alert chặn luồng UI và không style được). */
  onError?: (message: string) => void;
}

const SLIDE_WIDTH_IN = {
  "16:9": 13.333,
  "4:3": 10,
} as const;
const SLIDE_HEIGHT_IN = 7.5;
const CARD_TEXT_PAD_IN = 0.18;
const CARD_TEXT_PAD_TOP_IN = 0.20;
const CARD_TEXT_PAD_BOTTOM_IN = 0.16;
const CARD_BORDER_PT = 0.75;

const PREVIEW_PALETTES: Record<string, { subText: string; text: string }> = {
  Futuristic: { text: "#F6F8FB", subText: "#9AA3B5" },
  Minimalist: { text: "#F2F5F7", subText: "#A8B3BE" },
  Minimal: { text: "#F2F5F7", subText: "#A8B3BE" },
  Corporate: { text: "#FFFFFF", subText: "#9FB0C9" },
  CorporateMinimalist: { text: "#F8FAFC", subText: "#AAB6C8" },
  Creative: { text: "#FFFFFF", subText: "#D3C7E2" },
  Academic: { text: "#F4F7FA", subText: "#A7B3C2" },
};

function clampNumber(value: number | null | undefined, min: number, max: number): number {
  if (typeof value !== "number" || Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function hexToRgba(hex: string | null | undefined, alpha: number): string {
  if (!hex) return `rgba(255,255,255,${alpha})`;
  const normalized = hex.trim().replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) return `rgba(255,255,255,${alpha})`;
  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function bodyFontSize(titleSize: number): number {
  if (titleSize >= 40) return 11.5;
  if (titleSize >= 24) return 12.5;
  if (titleSize >= 18) return 11.2;
  if (titleSize >= 15) return 10.4;
  if (titleSize >= 13) return 9.8;
  return 9.2;
}

export const SlidePreview: React.FC<SlidePreviewProps> = ({
  data,
  cachedBlob,
  downloadFilename,
  onReset,
  onEditPrompt,
  onDownloadRequest,
  onError,
}) => {
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [isPlayingMorph, setIsPlayingMorph] = useState(false);
  const [showMorphDetails, setShowMorphDetails] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadSuccess, setDownloadSuccess] = useState(false);

  // Ref giữ timer reset trạng thái "Đã tải về" — được cleanup khi unmount
  // để tránh gọi setState trên component đã bị gỡ (memory leak).
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    return () => {
      if (successTimerRef.current) clearTimeout(successTimerRef.current);
    };
  }, []);

  const slideCanvasRef = useRef<HTMLDivElement | null>(null);
  const [slideCanvasWidth, setSlideCanvasWidth] = useState(0);

  useEffect(() => {
    const node = slideCanvasRef.current;
    if (!node || typeof ResizeObserver === "undefined") return;

    const updateSize = () => setSlideCanvasWidth(node.getBoundingClientRect().width);
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(node);
    return () => observer.disconnect();
  }, [currentSlideIndex, data.aspectRatio]);

  // Hiệu ứng pháo hoa khi sinh slide thành công
  useEffect(() => {
    confetti({
      particleCount: 90,
      spread: 75,
      origin: { y: 0.6 },
      colors: ["#8B5CF6", "#EC4899", "#06B6D4", "#10B981"],
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Vòng lặp trình chiếu tự động hiệu ứng Morph.
  // FIX: dùng ReturnType<typeof setInterval> (bản cũ ghi NodeJS.Timeout —
  // sai môi trường browser); chỉ chạy khi thực sự có slide.
  useEffect(() => {
    if (!isPlayingMorph || data.slides.length === 0) return;
    const interval = setInterval(() => {
      setCurrentSlideIndex((prev) => (prev + 1) % data.slides.length);
    }, 3500);
    return () => clearInterval(interval);
  }, [isPlayingMorph, data.slides.length]);

  const currentSlide: SlideItem | undefined =
    data.slides[currentSlideIndex] ?? data.slides[0];

  const handlePrev = () => {
    setCurrentSlideIndex((prev) => (prev > 0 ? prev - 1 : data.slides.length - 1));
  };

  const handleNext = () => {
    setCurrentSlideIndex((prev) => (prev < data.slides.length - 1 ? prev + 1 : 0));
  };

  const handleDownloadClick = async () => {
    setIsDownloading(true);

    try {
      if (cachedBlob) {
        // Tải trực tiếp từ Blob đã lưu sẵn trong RAM
        const filename = downloadFilename || `${data.presentationTitle.toLowerCase().replace(/\s+/g, "_")}_morph.pptx`;
        downloadBlob(cachedBlob, filename);
        setDownloadSuccess(true);
      } else if (onDownloadRequest) {
        // Gọi API tải file mới từ backend (hàm cha tự download ngay khi có blob)
        await onDownloadRequest();
        setDownloadSuccess(true);
      } else {
        console.warn("Không có blob cache và không có callback tải file từ backend.");
      }
    } catch (err) {
      console.error("Lỗi khi tải file:", err);
      // Thông báo lỗi thân thiện qua ErrorNotification thay vì alert() chặn UI
      onError?.(
        err instanceof Error
          ? `Lỗi khi tải file PPTX: ${err.message}`
          : "Đã xảy ra lỗi khi tải file PPTX. Vui lòng thử lại!"
      );
    } finally {
      setIsDownloading(false);
      // Hủy timer cũ (nếu có) trước khi đặt timer mới, tránh chồng chéo setState
      if (successTimerRef.current) clearTimeout(successTimerRef.current);
      successTimerRef.current = setTimeout(() => setDownloadSuccess(false), 4000);
    }
  };

  // Guard phòng thủ: backend đảm bảo >= 1 slide, nhưng nếu dữ liệu rỗng thì
  // render graceful thay vì crash ở currentSlide.morphDescription bên dưới.
  if (!currentSlide) {
    return (
      <div className="w-full max-w-5xl mx-auto p-6 rounded-2xl glass-panel text-center text-slate-400 text-sm">
        Chưa có dữ liệu slide để hiển thị.
      </div>
    );
  }

  const currentElements = currentSlide.elements ?? [];
  const slideWidthIn = SLIDE_WIDTH_IN[data.aspectRatio];
  const pxPerIn = slideCanvasWidth > 0 ? slideCanvasWidth / slideWidthIn : 67.2;
  const ptToPx = (pt: number) => Math.max(6, (pt / 72) * pxPerIn);
  const inToPx = (inch: number) => inch * pxPerIn;
  const palette = PREVIEW_PALETTES[data.style] ?? PREVIEW_PALETTES.Futuristic;
  const cardLikeElements = currentElements.filter((e) => ["card", "text", "shape", "metric"].includes(e.type));
  const primaryCardId = cardLikeElements.length >= 2 ? cardLikeElements[0]?.id : undefined;
  // Nền slide: backend có thể trả hex (nền đặc) HOẶC chuỗi CSS gradient
  // linear-gradient(...) cho slide mở bài/kết bài — chuỗi đó được dùng y nguyên
  // làm CSS `background` để preview khớp <a:gradFill> trong file PPTX thật.
  const slideBgValue = (currentSlide.bgColor || "").trim();
  const isGradientBg = /^linear-gradient\(/i.test(slideBgValue);
  const slideCanvasBgStyle: React.CSSProperties = isGradientBg
    ? { background: slideBgValue }
    : { backgroundColor: currentSlide.bgColor || "#0A0C12" };

  const renderBackendElement = (elem: BackendSlideElement, idx: number) => {
    const x = clampNumber(elem.x, 0, 100);
    const y = clampNumber(elem.y, 0, 100);
    const w = clampNumber(elem.width, 0.01, Math.max(0.01, 100 - x));
    const h = clampNumber(elem.height, 0.01, Math.max(0.01, 100 - y));
    const fontPt = elem.font_size ?? (elem.type === "footer" ? 9 : 12);
    const baseStyle: React.CSSProperties = {
      position: "absolute",
      left: `${x}%`,
      top: `${y}%`,
      width: `${w}%`,
      height: `${h}%`,
      color: elem.text_color || palette.text,
      fontFamily: "Segoe UI, Inter, ui-sans-serif, system-ui, sans-serif",
      fontSize: ptToPx(fontPt),
      lineHeight: elem.type === "heading" && fontPt >= 40 ? 1.04 : 1.12,
      zIndex: elem.type === "accent" ? 1 : elem.type === "footer" ? 5 : 3,
    };

    const borderRadius = elem.shape_type === "oval" ? "9999px" : inToPx(0.14);
    const border = elem.border_color
      ? `${Math.max(1, ptToPx(CARD_BORDER_PT))}px solid ${hexToRgba(elem.border_color, 0.55)}`
      : undefined;

    // QUAN TRỌNG: chỉ gán layoutId khi backend thật sự đánh dấu đây là
    // morph-anchor có chủ đích (`morph_id` tồn tại). Nếu fallback về `elem.id`
    // (chỉ số cục bộ trong 1 slide, lặp lại 1,2,3... ở mọi slide), Framer Motion
    // sẽ coi 2 shape KHÔNG liên quan ở 2 slide khác nhau là "cùng một object"
    // và tự động nội suy (FLIP animate) giữa vị trí/kích thước/nội dung của
    // chúng khi đổi slide -> gây hiệu ứng "chữ đè chữ, nhoè" trong lúc chuyển
    // slide hoặc khi demo Morph tự chạy (setInterval 3.5s).
    const morphLayoutId = elem.morph_id ? `morph-${elem.morph_id}` : undefined;

    // HOẠ TIẾT NỀN rất mờ (opacity 3-6%): chấm sao / lưới toạ độ / lattice —
    // cùng bộ motif theo chủ đề với file PPTX, nằm dưới mọi phần tử khác.
    // Không morph_id → không layoutId, không tham gia hiệu ứng chuyển slide.
    if (elem.type === "decoration") {
      return (
        <div
          key={`${elem.id}-${idx}`}
          style={{
            ...baseStyle,
            zIndex: 0,
            backgroundColor: elem.bg_color || "#8B5CF6",
            opacity: elem.opacity ?? 1,
            borderRadius: elem.shape_type === "oval" ? "9999px" : 2,
            pointerEvents: "none",
          }}
        />
      );
    }

    if (elem.type === "accent" || elem.type === "connector") {
      return (
        <motion.div
          key={`${elem.id}-${idx}`}
          layoutId={morphLayoutId}
          className="pointer-events-none"
          style={{
            ...baseStyle,
            backgroundColor: elem.bg_color || elem.accent_color || "#8B5CF6",
            borderRadius: elem.shape_type === "oval" ? "9999px" : 2,
          }}
        />
      );
    }

    if (elem.type === "badge") {
      return (
        <motion.div
          key={`${elem.id}-${idx}`}
          layoutId={morphLayoutId}
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.28 }}
          style={{
            ...baseStyle,
            backgroundColor: elem.bg_color || "#7C3AED",
            borderRadius,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 800,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textAlign: "center",
            padding: `0 ${inToPx(0.12)}px`,
          }}
        >
          {elem.content}
        </motion.div>
      );
    }

    if (elem.type === "heading" || elem.type === "kicker" || elem.type === "footer") {
      const isKicker = elem.type === "kicker";
      return (
        <motion.div
          key={`${elem.id}-${idx}`}
          layoutId={morphLayoutId}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          style={{
            ...baseStyle,
            display: "flex",
            alignItems: elem.type === "footer" ? "center" : "flex-start",
            justifyContent:
              elem.align === "right" ? "flex-end" : elem.align === "center" ? "center" : "flex-start",
            fontWeight: elem.type === "footer" ? 500 : 800,
            letterSpacing: isKicker ? "0.22em" : elem.type === "footer" ? "0.01em" : "-0.025em",
            textTransform: isKicker ? "uppercase" : undefined,
            textAlign: elem.align || "left",
            overflow: "hidden",
            whiteSpace: elem.type === "footer" ? "nowrap" : "normal",
          }}
        >
          {elem.content}
        </motion.div>
      );
    }

    const isCard = elem.type === "card" || elem.type === "metric" || elem.type === "text" || elem.type === "shape";
    if (isCard) {
      const isPrimary = elem.id === primaryCardId;
      const isStatCard = (elem.font_size ?? 0) >= 40;
      const isCta = elem.align === "center" && !elem.sub_text;
      // Biến thể thị giác do backend layout_engine chọn theo vai trò card —
      // đồng bộ 1:1 với PPTX builder (accent_top/accent_left/outline/cta).
      const variant = elem.variant || (isCta ? "cta" : "accent_top");
      const elemWidthIn = (w / 100) * slideWidthIn;
      const elemHeightIn = (h / 100) * SLIDE_HEIGHT_IN;
      const accentInsetPct = elemWidthIn > 0 ? (0.08 / elemWidthIn) * 100 : 0;
      const accentHeightPx = inToPx(isPrimary ? 0.075 : 0.045);
      const titleSizePx = ptToPx(fontPt);
      const statTitleH = Math.min(1.14, Math.max(0.72, elemHeightIn * 0.34));
      const statBodyH = Math.max(0.30, elemHeightIn - statTitleH - 0.16 - 0.74);
      const statTitleY = elemHeightIn >= 2.2 ? 0.54 : CARD_TEXT_PAD_TOP_IN;
      const statBodyY = Math.min(
        elemHeightIn - statBodyH - CARD_TEXT_PAD_BOTTOM_IN,
        statTitleY + statTitleH + 0.16
      );
      // Card outline: KHÔNG nền (slide bg xuyên qua) + viền mỏng màu accent —
      // phân cấp thị giác chính/phụ thay vì mọi card cùng 1 trọng lượng.
      const isOutline = variant === "outline";
      const cardBorder = isOutline
        ? `${Math.max(1, ptToPx(CARD_BORDER_PT * 1.3))}px solid ${hexToRgba(elem.accent_color || "#10B981", 0.5)}`
        : border;
      // Viền trái dày (accent_left) thay thanh màu trên đỉnh — 0.062" ~ 4.5px.
      const leftBarWidthPx = inToPx(0.062);

      return (
        <motion.div
          key={`${elem.id}-${idx}`}
          layoutId={morphLayoutId}
          initial={{ opacity: 0, scale: 0.985 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.34, delay: Math.min(idx * 0.015, 0.12) }}
          style={{
            ...baseStyle,
            backgroundColor: isOutline ? "transparent" : elem.bg_color || "#141827",
            border: cardBorder,
            borderRadius,
            overflow: "hidden",
            boxShadow: isOutline
              ? "none"
              : isPrimary
                ? "0 18px 42px rgba(0,0,0,0.20)"
                : "0 12px 30px rgba(0,0,0,0.15)",
          }}
        >
          {variant === "accent_top" && !isCta && elem.type !== "shape" && (
            <span
              style={{
                position: "absolute",
                left: `${accentInsetPct}%`,
                right: `${accentInsetPct}%`,
                top: inToPx(0.045),
                height: accentHeightPx,
                backgroundColor: elem.accent_color || "#10B981",
                borderRadius: 999,
              }}
            />
          )}

          {variant === "accent_left" && !isCta && elem.type !== "shape" && (
            <span
              style={{
                position: "absolute",
                left: inToPx(0.02),
                top: inToPx(0.1),
                bottom: inToPx(0.1),
                width: leftBarWidthPx,
                backgroundColor: elem.accent_color || "#10B981",
                borderRadius: 999,
              }}
            />
          )}

          {elem.type !== "shape" && isStatCard && (
            <>
              {elem.icon && (
                <span
                  style={{
                    position: "absolute",
                    top: inToPx(0.16),
                    right: inToPx(0.16),
                    fontSize: ptToPx(16),
                    lineHeight: 1,
                    opacity: 0.92,
                  }}
                >
                  {elem.icon}
                </span>
              )}
              <div
                style={{
                  position: "absolute",
                  left: inToPx(CARD_TEXT_PAD_IN),
                  right: inToPx(CARD_TEXT_PAD_IN),
                  top: inToPx(statTitleY),
                  height: inToPx(statTitleH),
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: elem.text_color || palette.text,
                  fontSize: titleSizePx,
                  fontWeight: 900,
                  lineHeight: 0.94,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "clip",
                  letterSpacing: "-0.055em",
                }}
              >
                {elem.content}
              </div>
              {elem.sub_text && (
                <div
                  style={{
                    position: "absolute",
                    left: inToPx(CARD_TEXT_PAD_IN),
                    right: inToPx(CARD_TEXT_PAD_IN),
                    top: inToPx(statBodyY),
                    height: inToPx(statBodyH),
                    color: palette.subText,
                    fontSize: ptToPx(bodyFontSize(fontPt)),
                    lineHeight: 1.12,
                    textAlign: "center",
                    overflow: "hidden",
                  }}
                >
                  {elem.sub_text}
                </div>
              )}
            </>
          )}

          {elem.type !== "shape" && !isStatCard && (
            <div
              style={{
                position: "absolute",
                inset: isCta
                  ? `${inToPx(0.08)}px ${inToPx(CARD_TEXT_PAD_IN)}px`
                  : `${inToPx(CARD_TEXT_PAD_TOP_IN)}px ${inToPx(CARD_TEXT_PAD_IN)}px ${inToPx(CARD_TEXT_PAD_BOTTOM_IN)}px`,
                // accent_left: chừa thêm bên trái cho dải viền dày.
                paddingLeft: variant === "accent_left" ? leftBarWidthPx + inToPx(0.08) : undefined,
                display: "flex",
                flexDirection: "column",
                justifyContent: isCta ? "center" : "flex-start",
                textAlign: elem.align || "left",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  color: elem.text_color || palette.text,
                  fontSize: titleSizePx,
                  fontWeight: 800,
                  lineHeight: 1.08,
                  letterSpacing: "-0.015em",
                  overflow: "hidden",
                }}
              >
                {elem.icon && (
                  <span style={{ marginRight: "0.32em", color: elem.accent_color || "#10B981" }}>
                    {elem.icon}
                  </span>
                )}
                {elem.content}
              </div>
              {elem.sub_text && (
                <div
                  style={{
                    marginTop: inToPx(0.07),
                    color: palette.subText,
                    fontSize: ptToPx(bodyFontSize(fontPt)),
                    lineHeight: 1.12,
                    overflow: "hidden",
                  }}
                >
                  {elem.sub_text}
                </div>
              )}
            </div>
          )}
        </motion.div>
      );
    }

    return null;
  };

  return (
    <div className="w-full max-w-5xl mx-auto space-y-6">
      {/* Top Bar Header Kết Quả */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 rounded-2xl glass-panel">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
              <CheckCircle className="w-3.5 h-3.5" />
              Đã tạo thành công {data.totalSlides} Slide với Morph
            </span>
            <span className="text-xs text-slate-400">
              Tỉ lệ: {data.aspectRatio} &bull; Phong cách: {data.style}
            </span>
          </div>
          <h2 className="text-lg sm:text-xl font-bold text-white mt-1">
            {data.presentationTitle}
          </h2>
        </div>

        {/* Cụm nút hành động */}
        <div className="flex items-center gap-2.5 w-full sm:w-auto">
          <button
            onClick={onEditPrompt}
            className="flex-1 sm:flex-initial px-3.5 py-2 text-xs font-medium text-slate-300 hover:text-white rounded-xl bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.08] transition-colors"
          >
            Sửa Prompt
          </button>
          <button
            onClick={onReset}
            className="flex-1 sm:flex-initial px-3.5 py-2 text-xs font-medium text-slate-300 hover:text-white rounded-xl bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.08] transition-colors flex items-center justify-center gap-1.5"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Tạo mới</span>
          </button>
          <button
            onClick={handleDownloadClick}
            disabled={isDownloading}
            className="flex-1 sm:flex-initial px-5 py-2.5 text-xs font-semibold text-white rounded-xl btn-gradient-morph shadow-lg flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
          >
            {downloadSuccess ? (
              <>
                <FileCheck2 className="w-4 h-4 text-emerald-300" />
                <span>Đã tải về .pptx!</span>
              </>
            ) : isDownloading ? (
              <>
                <Sparkles className="w-4 h-4 animate-spin" />
                <span>Đang tải xuống...</span>
              </>
            ) : (
              <>
                <Download className="w-4 h-4" />
                <span>Tải file .pptx có Morph</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Sân khấu Canvas trình chiếu Morph chính */}
      <div className="relative rounded-2xl glass-panel p-4 sm:p-6 border border-purple-500/20 shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/[0.06] text-xs text-slate-300">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-white">
              Slide {currentSlideIndex + 1} / {data.slides.length}
            </span>
            <span className="text-slate-500">&bull;</span>
            <span className="text-purple-400 font-medium line-clamp-1">
              Hiệu ứng: {currentSlide.morphDescription}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsPlayingMorph(!isPlayingMorph)}
              className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 text-xs font-medium transition-all ${
                isPlayingMorph
                  ? "bg-purple-600 text-white shadow-md shadow-purple-600/30"
                  : "bg-white/[0.05] text-slate-300 hover:bg-white/[0.1]"
              }`}
            >
              {isPlayingMorph ? (
                <>
                  <Pause className="w-3.5 h-3.5" />
                  <span>Dừng Demo Morph</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Xem Demo Chuyển Slide (Morph)</span>
                </>
              )}
            </button>

            <button
              onClick={() => setShowMorphDetails(!showMorphDetails)}
              className="p-1.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-slate-300 transition-colors"
              title="Xem ma trận Morph Anchors"
            >
              <Sliders className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Khung viewport slide (Tỉ lệ 16:9 hoặc 4:3) — render từ tọa độ backend */}
        <div className="w-full flex items-center justify-center bg-black/60 rounded-xl p-2 sm:p-4 border border-white/[0.05]">
          <div
            ref={slideCanvasRef}
            className={`w-full max-w-4xl relative rounded-xl overflow-hidden border border-white/[0.10] shadow-2xl transition-all duration-500 ${
              data.aspectRatio === "4:3" ? "slide-ratio-4-3" : "slide-ratio-16-9"
            }`}
            style={slideCanvasBgStyle}
          >
            {currentElements.length > 0 ? (
              currentElements.map((elem, idx) => renderBackendElement(elem, idx))
            ) : (
              <div className="absolute inset-0 p-8 flex flex-col justify-center text-center">
                <h3 className="text-2xl font-extrabold text-white">{currentSlide.title}</h3>
                {currentSlide.subtitle && (
                  <p className="mt-3 text-sm text-slate-400">{currentSlide.subtitle}</p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Chỉ báo trạng thái Morph Anchor — nằm ngoài canvas để preview khớp PPTX */}
        <motion.div
          layoutId="morph-active-indicator"
          className="mt-4 p-2.5 rounded-lg bg-purple-950/30 border border-purple-500/30 flex items-center justify-between text-[11px] text-purple-300"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="w-2 h-2 rounded-full bg-purple-400 animate-ping shrink-0" />
            <span className="truncate">
              <strong>Morph Anchor Active:</strong> {currentSlide.morphAnchors?.[0]?.name || "Seamless Shape Transition"}
            </span>
          </div>
          <span className="text-[10px] bg-purple-500/20 px-2 py-0.5 rounded font-mono shrink-0">
            {currentSlide.backendLayoutType || currentSlide.morphAnchors?.[0]?.transitionType || "translate & scale"}
          </span>
        </motion.div>

        {/* Thanh điều khiển & Thumbnails */}
        <div className="mt-5 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <button
              onClick={handlePrev}
              className="p-2 rounded-xl bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.08] text-white transition-colors"
              title="Slide trước"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>

            <span className="text-xs text-slate-300 font-mono px-2">
              {currentSlideIndex + 1} / {data.slides.length}
            </span>

            <button
              onClick={handleNext}
              className="p-2 rounded-xl bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.08] text-white transition-colors"
              title="Slide kế tiếp"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>

          <div className="flex items-center gap-2 overflow-x-auto max-w-full pb-1">
            {data.slides.map((slide, idx) => {
              const isSelected = idx === currentSlideIndex;
              return (
                <button
                  key={slide.id}
                  onClick={() => setCurrentSlideIndex(idx)}
                  className={`group relative flex-shrink-0 w-24 h-14 rounded-lg border transition-all text-left p-1.5 overflow-hidden ${
                    isSelected
                      ? "border-purple-500 bg-purple-950/40 shadow-md shadow-purple-500/20 ring-1 ring-purple-500"
                      : "border-white/[0.08] bg-black/40 hover:border-white/[0.2]"
                  }`}
                >
                  <div className="text-[9px] font-bold text-slate-400 group-hover:text-slate-200">
                    Slide {idx + 1}
                  </div>
                  <div className="text-[10px] font-semibold text-slate-200 truncate mt-0.5">
                    {slide.title}
                  </div>
                  <div className="absolute bottom-1 right-1.5 w-1.5 h-1.5 rounded-full bg-cyan-400 opacity-60" />
                </button>
              );
            })}
          </div>
        </div>

        {/* Bảng chi tiết Morph Anchors */}
        {showMorphDetails && (
          <div className="mt-5 p-4 rounded-xl bg-purple-950/20 border border-purple-500/30 text-xs text-slate-300 space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="font-semibold text-white flex items-center gap-2">
                <Layers className="w-4 h-4 text-purple-400" />
                <span>Chi tiết tọa độ và thuộc tính Morphing</span>
              </h4>
              <span className="text-[10px] text-purple-300 font-mono">
                PowerPoint Morph XML Tag: &lt;p:transition&gt;&lt;p:morph/&gt;
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06]">
                <span className="text-[11px] font-semibold text-slate-200 block mb-1">
                  Đặc tính biến đổi giữa Slide {currentSlideIndex + 1} và Slide{" "}
                  {currentSlideIndex < data.slides.length - 1 ? currentSlideIndex + 2 : 1}:
                </span>
                <p className="text-slate-400 text-[11px] leading-relaxed">
                  {currentSlide.morphDescription}
                </p>
              </div>

              {currentSlide.speakerNotes && (
                <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06]">
                  <span className="text-[11px] font-semibold text-slate-200 block mb-1">
                    Ghi chú người thuyết trình (Speaker Notes):
                  </span>
                  <p className="text-slate-400 text-[11px] leading-relaxed italic">
                    "{currentSlide.speakerNotes}"
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Thông số tính năng */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
        <div className="p-3.5 rounded-xl glass-card flex items-center gap-3">
          <div className="p-2 rounded-lg bg-purple-500/10 text-purple-400">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <div className="font-semibold text-slate-200">Morphing Tự Động</div>
            <div className="text-slate-400 text-[11px]">Tương thích PowerPoint 2019, 365 & Office Web</div>
          </div>
        </div>

        <div className="p-3.5 rounded-xl glass-card flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400">
            <Layers className="w-4 h-4" />
          </div>
          <div>
            <div className="font-semibold text-slate-200">Định Dạng Chuẩn PPTX</div>
            <div className="text-slate-400 text-[11px]">Chỉnh sửa văn bản và màu sắc 100% trong PowerPoint</div>
          </div>
        </div>

        <div className="p-3.5 rounded-xl glass-card flex items-center gap-3">
          <div className="p-2 rounded-lg bg-pink-500/10 text-pink-400">
            <Download className="w-4 h-4" />
          </div>
          <div>
            <div className="font-semibold text-slate-200">Không Cần Cài Add-in</div>
            <div className="text-slate-400 text-[11px]">Mở trực tiếp trên mọi thiết bị máy tính</div>
          </div>
        </div>
      </div>
    </div>
  );
};

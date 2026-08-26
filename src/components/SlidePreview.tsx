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
  TrendingUp, 
  CheckCircle,
  Sliders
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import confetti from "canvas-confetti";
import { SlidePreviewData, SlideItem } from "@/types";
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

        {/* Khung viewport slide (Tỉ lệ 16:9 hoặc 4:3) */}
        <div className="w-full flex items-center justify-center bg-black/60 rounded-xl p-2 sm:p-4 border border-white/[0.05]">
          <div
            className={`w-full max-w-4xl relative rounded-xl overflow-hidden bg-gradient-to-br from-[#10121A] via-[#161926] to-[#0A0C13] border border-white/[0.12] shadow-2xl flex flex-col justify-between p-6 sm:p-10 transition-all duration-500 ${
              data.aspectRatio === "4:3" ? "slide-ratio-4-3" : "slide-ratio-16-9"
            }`}
          >
            <div className="absolute inset-0 bg-grid-pattern opacity-20 pointer-events-none" />

            {/* Header của slide */}
            <div className="relative z-10 flex items-start justify-between gap-4">
              <div className="space-y-1">
                {currentSlide.section && (
                  <motion.span
                    layoutId="slide-section"
                    className="inline-block text-[10px] font-bold uppercase tracking-[0.25em] text-cyan-300/90"
                  >
                    {currentSlide.section}
                  </motion.span>
                )}
                <div className="flex items-center gap-2">
                  {currentSlide.badge && (
                    <motion.span
                      layoutId="slide-badge"
                      className="inline-block px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30"
                    >
                      {currentSlide.badge}
                    </motion.span>
                  )}
                </div>
                <AnimatePresence mode="wait">
                  <motion.h3
                    key={currentSlide.id + "-title"}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.35 }}
                    className="text-xl sm:text-2xl md:text-3xl font-extrabold text-white tracking-tight"
                  >
                    {currentSlide.title}
                  </motion.h3>
                </AnimatePresence>
                {currentSlide.subtitle && (
                  <motion.p
                    key={currentSlide.id + "-sub"}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="text-xs sm:text-sm text-slate-400 font-medium"
                  >
                    {currentSlide.subtitle}
                  </motion.p>
                )}
              </div>

              <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-white/[0.04] border border-white/[0.08] text-[10px] text-slate-400 shrink-0">
                <Sparkles className="w-3 h-3 text-cyan-400" />
                <span>ExoticMorph PPTX</span>
              </div>
            </div>

            {/* Nội dung thân slide với hiệu ứng Morph động */}
            <div className="relative z-10 my-auto py-4">
              {/* Thẻ chỉ số Metrics */}
              {currentSlide.metrics && currentSlide.metrics.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
                  {currentSlide.metrics.map((metric, idx) => (
                    <motion.div
                      key={`metric-${idx}-${currentSlide.id}`}
                      layoutId={`morph-card-${idx}`}
                      initial={{ scale: 0.95, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      transition={{ duration: 0.45, delay: idx * 0.08 }}
                      className="p-4 rounded-xl bg-white/[0.04] border border-white/[0.08] hover:border-purple-500/40 transition-colors backdrop-blur-md relative group overflow-hidden"
                    >
                      <div className="text-xs text-slate-400 mb-1">{metric.label}</div>
                      <div className="text-2xl sm:text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-white via-purple-100 to-purple-300">
                        {metric.value}
                      </div>
                      {metric.change && (
                        <div className="mt-2 text-[11px] font-semibold text-emerald-400 flex items-center gap-1">
                          <TrendingUp className="w-3 h-3" />
                          <span>{metric.change}</span>
                        </div>
                      )}
                      <div className="absolute top-0 right-0 w-16 h-16 bg-purple-500/5 rounded-full blur-xl group-hover:bg-purple-500/15 transition-all" />
                    </motion.div>
                  ))}
                </div>
              )}

              {/* Thẻ nội dung hai phần: thông điệp cụ thể + đoạn diễn giải chi tiết */}
              {currentSlide.cards && currentSlide.cards.length > 0 && (
                <div
                  className={`grid gap-3 ${
                    currentSlide.cards.length === 1
                      ? "grid-cols-1"
                      : currentSlide.cards.length === 2
                      ? "grid-cols-1 sm:grid-cols-2"
                      : currentSlide.cards.length === 3
                      ? "grid-cols-1 sm:grid-cols-3"
                      : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4"
                  }`}
                >
                  {currentSlide.cards.map((card, idx) => (
                    <motion.div
                      key={`card-${idx}-${currentSlide.id}`}
                      layoutId={`morph-card-${idx}`}
                      initial={{ scale: 0.96, opacity: 0, y: 8 }}
                      animate={{ scale: 1, opacity: 1, y: 0 }}
                      transition={{ duration: 0.4, delay: idx * 0.06 }}
                      className="relative p-4 rounded-xl bg-white/[0.04] border border-white/[0.08] overflow-hidden backdrop-blur-md group"
                    >
                      {card.accentColor && (
                        <span
                          className="absolute top-0 left-0 right-0 h-[3px]"
                          style={{ backgroundColor: card.accentColor }}
                        />
                      )}
                      <div className="flex items-center gap-2 mb-2">
                        {card.step && (
                          <span
                            className="w-5 h-5 rounded-full text-[11px] font-bold flex items-center justify-center shrink-0 text-white"
                            style={{ backgroundColor: card.accentColor || "#8B5CF6" }}
                          >
                            {card.step}
                          </span>
                        )}
                        <h4 className="text-sm sm:text-base font-bold text-white leading-snug">
                          {card.title}
                        </h4>
                      </div>
                      <p className="text-xs sm:text-[13px] text-slate-400 leading-relaxed">
                        {card.body}
                      </p>
                    </motion.div>
                  ))}
                </div>
              )}

              {/* Fallback danh sách luận điểm (khi backend trả text/heading) */}
              {(!currentSlide.cards || currentSlide.cards.length === 0) &&
                currentSlide.bulletPoints &&
                currentSlide.bulletPoints.length > 0 && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {currentSlide.bulletPoints.map((point, idx) => (
                      <motion.div
                        key={`bullet-${idx}-${currentSlide.id}`}
                        layoutId={`morph-bullet-${idx}`}
                        initial={{ x: -10, opacity: 0 }}
                        animate={{ x: 0, opacity: 1 }}
                        transition={{ duration: 0.4, delay: idx * 0.06 }}
                        className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.06] flex items-start gap-3"
                      >
                        <span className="w-5 h-5 rounded-full bg-purple-500/20 text-purple-300 text-xs font-bold flex items-center justify-center shrink-0 mt-0.5 border border-purple-500/30">
                          {idx + 1}
                        </span>
                        <p className="text-xs sm:text-sm text-slate-200 leading-relaxed font-normal">
                          {point}
                        </p>
                      </motion.div>
                    ))}
                  </div>
                )}

              {/* Chỉ báo trạng thái Morph Anchor */}
              <motion.div
                layoutId="morph-active-indicator"
                className="mt-4 p-2.5 rounded-lg bg-purple-950/30 border border-purple-500/30 flex items-center justify-between text-[11px] text-purple-300"
              >
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-purple-400 animate-ping" />
                  <span>
                    <strong>Morph Anchor Active:</strong> {currentSlide.morphAnchors?.[0]?.name || "Seamless Shape Transition"}
                  </span>
                </div>
                <span className="text-[10px] bg-purple-500/20 px-2 py-0.5 rounded font-mono">
                  {currentSlide.morphAnchors?.[0]?.transitionType || "translate & scale"}
                </span>
              </motion.div>
            </div>

            {/* Footer của slide */}
            <div className="relative z-10 pt-3 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400">
              <div className="flex items-center gap-2">
                <span>{data.presentationTitle}</span>
                {currentSlide.tags?.map((tag) => (
                  <span key={tag} className="hidden sm:inline-block px-1.5 py-0.5 rounded bg-white/[0.05] text-[10px]">
                    #{tag}
                  </span>
                ))}
              </div>
              <span className="font-mono font-semibold text-slate-300">
                0{currentSlideIndex + 1} / 0{data.slides.length}
              </span>
            </div>
          </div>
        </div>

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

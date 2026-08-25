"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  Sparkles,
  Cpu,
  Layers,
  FileCode,
  CheckCircle2,
  Loader2
} from "lucide-react";
import { GenerationProgressStep } from "@/types";

/**
 * Props progressPercentage/currentStepIndex của bản cũ là props CHẾT (khai báo
 * nhưng không bao giờ đọc) — đã xóa để API component trung thực.
 */
type LoadingProgressProps = Record<string, never>;

const STEPS_DATA: Omit<GenerationProgressStep, "completed" | "current">[] = [
  {
    id: "step-1",
    label: "Phân tích cấu trúc & Luồng nội dung",
    detail: "AI đang bóc tách ý tưởng, chia bố cục và xác định thông điệp cốt lõi từng slide...",
    progressPercentage: 25,
  },
  {
    id: "step-2",
    label: "Thiết kế Visual & Phân cấp thông tin",
    detail: "Định dạng thẻ chỉ số KPI, lưới so sánh và cấu trúc đồ họa trực quan...",
    progressPercentage: 55,
  },
  {
    id: "step-3",
    label: "Tính toán tọa độ Morphing Anchors",
    detail: "Ánh xạ tọa độ đối tượng (x, y, w, h) giữa các slide để chuyển động Morph không bị giật...",
    progressPercentage: 85,
  },
  {
    id: "step-4",
    label: "Biên dịch PowerPoint OpenXML (.pptx)",
    detail: "Đóng gói tệp slide chuẩn Microsoft Office với hiệu ứng Morph kích hoạt sẵn...",
    progressPercentage: 100,
  },
];

export const LoadingProgress: React.FC<LoadingProgressProps> = () => {
  const [percent, setPercent] = useState(10);
  // Giữ interval trong ref để chủ động dừng hẳn khi đã đạt mốc 98% (bản cũ
  // để interval chạy vĩnh viễn trong suốt thời gian chờ -> tốn CPU vô ích).
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Mô phỏng tiến độ tăng dần (UI progress giả trong lúc Backend xử lý).
    // Lưu ý: updater PHẢI thuần (pure) — bản cũ gọi setActiveStep() ngay bên
    // trong setPercent() là anti-pattern: React StrictMode double-invoke
    // updater sẽ gây hiệu ứng phụ chồng chéo. Bước hiện tại được suy ra từ
    // percent lúc render thay vì lưu 2 state song song.
    intervalRef.current = setInterval(() => {
      setPercent((prev) => {
        if (prev >= 98) return prev;
        const step = prev < 30 ? 2 : prev < 65 ? 2.5 : prev < 90 ? 2 : 0.5;
        return Math.min(98, prev + step);
      });
    }, 70);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  // Dừng hẳn interval khi tiến độ đã chạm trần 98%.
  useEffect(() => {
    if (percent >= 98 && intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, [percent]);

  // Suy ra bước đang chạy từ % (single source of truth).
  const activeStep = percent < 30 ? 0 : percent < 65 ? 1 : percent < 90 ? 2 : 3;

  const getStepIcon = (index: number) => {
    switch (index) {
      case 0:
        return <Cpu className="w-4 h-4" />;
      case 1:
        return <Layers className="w-4 h-4" />;
      case 2:
        return <Sparkles className="w-4 h-4" />;
      case 3:
        return <FileCode className="w-4 h-4" />;
      default:
        return <Sparkles className="w-4 h-4" />;
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto my-8">
      {/* Container */}
      <div className="relative rounded-2xl glass-panel p-6 sm:p-8 border border-purple-500/30 shadow-2xl overflow-hidden">
        {/* Glow ambient background */}
        <div className="absolute -right-20 -top-20 w-64 h-64 bg-purple-600/20 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -left-20 -bottom-20 w-64 h-64 bg-cyan-600/20 rounded-full blur-3xl pointer-events-none" />

        {/* Header with Pulsing AI Core */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="relative flex items-center justify-center w-12 h-12 rounded-xl bg-purple-500/10 border border-purple-500/30 text-purple-400">
              <Loader2 className="w-6 h-6 animate-spin" />
              <div className="absolute inset-0 rounded-xl bg-purple-500/20 animate-ping opacity-30" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                <span>AI đang khởi tạo bản trình chiếu Morph...</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Đang xử lý thuật toán tối ưu hóa vector hình học và liên kết slide
              </p>
            </div>
          </div>

          {/* Percentage badge */}
          <div className="flex items-center gap-2 self-start sm:self-center px-3 py-1.5 rounded-full bg-purple-500/10 border border-purple-500/30 text-purple-300 font-mono text-sm font-bold">
            <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse" />
            <span>{Math.floor(percent)}%</span>
          </div>
        </div>

        {/* Main Progress Bar */}
        <div className="w-full h-2.5 bg-black/50 rounded-full overflow-hidden p-[2px] border border-white/[0.08] mb-8">
          <div
            className="h-full rounded-full bg-gradient-to-r from-purple-500 via-pink-500 to-cyan-400 transition-all duration-300 relative overflow-hidden"
            style={{ width: `${percent}%` }}
          >
            <div className="absolute inset-0 bg-white/20 animate-shimmer" />
          </div>
        </div>

        {/* Step-by-Step Milestones */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-8">
          {STEPS_DATA.map((step, idx) => {
            const isCompleted = activeStep > idx || percent >= 98;
            const isCurrent = activeStep === idx && percent < 98;

            return (
              <div
                key={step.id}
                className={`p-3.5 rounded-xl border transition-all duration-300 flex items-start gap-3 ${
                  isCompleted
                    ? "bg-emerald-950/20 border-emerald-500/30 text-slate-200"
                    : isCurrent
                    ? "bg-purple-950/30 border-purple-500/50 text-white shadow-lg shadow-purple-950/50"
                    : "bg-white/[0.01] border-white/[0.04] text-slate-500 opacity-60"
                }`}
              >
                <div
                  className={`p-2 rounded-lg mt-0.5 shrink-0 ${
                    isCompleted
                      ? "bg-emerald-500/20 text-emerald-400"
                      : isCurrent
                      ? "bg-purple-500/20 text-purple-300 animate-pulse"
                      : "bg-white/[0.05] text-slate-500"
                  }`}
                >
                  {isCompleted ? (
                    <CheckCircle2 className="w-4 h-4" />
                  ) : (
                    getStepIcon(idx)
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold">
                      {idx + 1}. {step.label}
                    </span>
                    {isCurrent && (
                      <span className="text-[10px] font-medium text-purple-300 bg-purple-500/20 px-1.5 py-0.5 rounded">
                        Đang chạy
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">
                    {step.detail}
                  </p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Skeleton Morph Slide Preview Placeholder */}
        <div className="border border-white/[0.08] rounded-xl p-4 bg-black/40">
          <div className="flex items-center justify-between mb-3 text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
              Xem trước ma trận Morph đang tính toán...
            </span>
            <span className="font-mono text-[11px]">Morph Anchors: 14/14</span>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="h-20 rounded-lg bg-white/[0.03] border border-white/[0.06] p-2.5 animate-pulse flex flex-col justify-between">
              <div className="w-1/2 h-2.5 bg-white/10 rounded" />
              <div className="space-y-1">
                <div className="w-full h-2 bg-white/5 rounded" />
                <div className="w-3/4 h-2 bg-white/5 rounded" />
              </div>
            </div>
            <div className="h-20 rounded-lg bg-purple-500/[0.06] border border-purple-500/20 p-2.5 animate-pulse flex flex-col justify-between">
              <div className="w-2/3 h-2.5 bg-purple-400/20 rounded" />
              <div className="flex gap-2">
                <div className="w-1/2 h-4 bg-purple-400/10 rounded" />
                <div className="w-1/2 h-4 bg-cyan-400/10 rounded" />
              </div>
            </div>
            <div className="h-20 rounded-lg bg-white/[0.03] border border-white/[0.06] p-2.5 animate-pulse flex flex-col justify-between">
              <div className="w-1/3 h-2.5 bg-white/10 rounded" />
              <div className="space-y-1">
                <div className="w-4/5 h-2 bg-white/5 rounded" />
                <div className="w-1/2 h-2 bg-white/5 rounded" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

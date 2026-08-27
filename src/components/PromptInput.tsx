"use client";

import React, { useState } from "react";
import { 
  Wand2, 
  Sparkles, 
  LayoutList, 
  Ratio, 
  RotateCcw,
  SlidersHorizontal,
  Info
} from "lucide-react";
import { PromptFormData, SlideCountOption, AspectRatioOption } from "@/types";

interface PromptInputProps {
  formData: PromptFormData;
  onChange: (data: PromptFormData) => void;
  onSubmit: () => void;
  isLoading: boolean;
}

export const PromptInput: React.FC<PromptInputProps> = ({
  formData,
  onChange,
  onSubmit,
  isLoading,
}) => {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange({ ...formData, topic: e.target.value });
  };

  const handleSlideCountChange = (count: SlideCountOption) => {
    onChange({ ...formData, slideCount: count });
  };

  const handleAspectRatioChange = (ratio: AspectRatioOption) => {
    onChange({ ...formData, aspectRatio: ratio });
  };


  const handleClear = () => {
    onChange({
      ...formData,
      topic: "",
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl + Enter or Cmd + Enter to submit
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (formData.topic.trim().length > 0 && !isLoading) {
        onSubmit();
      }
    }
  };

  const isFormValid = formData.topic.trim().length >= 5;

  return (
    <div className="w-full max-w-4xl mx-auto">
      {/* Main Glassmorphism Container */}
      <div className="relative rounded-2xl glass-panel p-5 sm:p-7 shadow-2xl border border-white/[0.1] overflow-hidden">
        {/* Top Glow Accent Bar */}
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-purple-500 via-pink-500 to-cyan-500" />

        {/* Input Header */}
        <div className="flex items-center justify-between mb-3">
          <label 
            htmlFor="prompt-textarea"
            className="flex items-center gap-2 text-sm font-semibold text-slate-200"
          >
            <Sparkles className="w-4 h-4 text-purple-400" />
            <span>Mô tả ý tưởng hoặc dán dàn ý thuyết trình</span>
          </label>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            {formData.topic.length > 0 && (
              <button
                type="button"
                onClick={handleClear}
                className="hover:text-slate-200 flex items-center gap-1 transition-colors px-2 py-0.5 rounded hover:bg-white/[0.05]"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Xóa trắng</span>
              </button>
            )}
            <span className="font-mono">{formData.topic.length}/1000</span>
          </div>
        </div>

        {/* Textarea */}
        <div className="relative group">
          <textarea
            id="prompt-textarea"
            rows={4}
            maxLength={1000}
            disabled={isLoading}
            value={formData.topic}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            placeholder="Ví dụ: Tạo bài thuyết trình 5 slide giới thiệu kiến trúc AI ExoticMorph, cơ chế ánh xạ tọa độ Morphing giữa các slide, cấu trúc pipeline biên dịch PPTX XML và demo các hiệu ứng chuyển đổi mượt mà..."
            className="w-full px-4 py-3.5 rounded-xl glass-input text-slate-100 placeholder-slate-500 text-sm sm:text-base leading-relaxed resize-y min-h-[110px] focus:outline-none"
          />
        </div>

        {/* Selectors Bar */}
        <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
          {/* Slide Count Selector */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
              <LayoutList className="w-3.5 h-3.5 text-purple-400" />
              <span>Số lượng slide</span>
            </div>
            <div className="grid grid-cols-3 gap-1.5 p-1 rounded-xl bg-black/40 border border-white/[0.06]">
              {([3, 5, 10] as SlideCountOption[]).map((count) => {
                const isActive = formData.slideCount === count;
                return (
                  <button
                    key={count}
                    type="button"
                    disabled={isLoading}
                    onClick={() => handleSlideCountChange(count)}
                    className={`py-1.5 text-xs font-medium rounded-lg transition-all ${
                      isActive
                        ? "bg-purple-600 text-white shadow-md shadow-purple-600/30"
                        : "text-slate-400 hover:text-white hover:bg-white/[0.05]"
                    }`}
                  >
                    {count} Slide{count > 1 ? "s" : ""}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Aspect Ratio Selector */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
              <Ratio className="w-3.5 h-3.5 text-cyan-400" />
              <span>Tỉ lệ slide</span>
            </div>
            <div className="grid grid-cols-2 gap-1.5 p-1 rounded-xl bg-black/40 border border-white/[0.06]">
              {(["16:9", "4:3"] as AspectRatioOption[]).map((ratio) => {
                const isActive = formData.aspectRatio === ratio;
                return (
                  <button
                    key={ratio}
                    type="button"
                    disabled={isLoading}
                    onClick={() => handleAspectRatioChange(ratio)}
                    className={`py-1.5 text-xs font-medium rounded-lg transition-all ${
                      isActive
                        ? "bg-cyan-600 text-white shadow-md shadow-cyan-600/30"
                        : "text-slate-400 hover:text-white hover:bg-white/[0.05]"
                    }`}
                  >
                    {ratio} {ratio === "16:9" ? "(Chuẩn)" : "(Cổ điển)"}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="sm:col-span-2 rounded-xl bg-white/[0.025] border border-white/[0.06] px-3.5 py-2.5 text-xs text-slate-400 flex items-start gap-2">
            <Sparkles className="w-3.5 h-3.5 text-pink-400 mt-0.5 shrink-0" />
            <span>AI tự phân tích prompt và chọn phong cách phù hợp nhất (Futuristic, Minimalist, Corporate/CorporateMinimalist, Creative hoặc Academic) khi gửi payload <code className="text-slate-300 font-mono">style: AUTO</code>.</span>
          </div>
        </div>

        {/* Advanced Options Toggle */}
        <div className="mt-4 pt-3 border-t border-white/[0.06] flex flex-wrap items-center justify-between gap-3 text-xs">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-slate-400 hover:text-purple-300 transition-colors"
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span>{showAdvanced ? "Ẩn tùy chọn nâng cao" : "Thêm tùy chọn tạo Morph nâng cao"}</span>
          </button>

          <div className="flex items-center gap-1.5 text-slate-500">
            <Info className="w-3.5 h-3.5 text-purple-400" />
            <span>Nhấn <kbd className="px-1.5 py-0.5 rounded bg-white/[0.08] font-mono text-[10px] text-slate-300">Ctrl + Enter</kbd> để tạo nhanh</span>
          </div>
        </div>

        {/* Collapsible Advanced Settings */}
        {showAdvanced && (
          <div className="mt-3 p-3 rounded-xl bg-white/[0.02] border border-white/[0.06] flex flex-wrap gap-4 text-xs text-slate-300 animate-fadeIn">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={formData.includeSpeakerNotes ?? true}
                onChange={(e) => onChange({ ...formData, includeSpeakerNotes: e.target.checked })}
                className="rounded border-white/20 text-purple-600 focus:ring-purple-500/50 bg-black/40"
              />
              <span>Tự động sinh lời dẫn người thuyết trình (Speaker Notes)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                defaultChecked
                className="rounded border-white/20 text-purple-600 focus:ring-purple-500/50 bg-black/40"
              />
              <span>Tối ưu hóa vector hình học cho chuyển động Morph 60 FPS</span>
            </label>
          </div>
        )}

        {/* Generate Action Button */}
        <div className="mt-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="text-xs text-slate-400 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>AI Morph Engine v2.4 sẵn sàng</span>
          </div>

          <button
            type="button"
            disabled={!isFormValid || isLoading}
            onClick={onSubmit}
            className={`w-full sm:w-auto px-8 py-3.5 rounded-xl font-semibold text-sm flex items-center justify-center gap-2.5 transition-all duration-300 ${
              isFormValid && !isLoading
                ? "btn-gradient-morph text-white shadow-lg cursor-pointer transform hover:scale-[1.02] active:scale-[0.98]"
                : "bg-slate-800 text-slate-500 cursor-not-allowed border border-white/[0.05]"
            }`}
          >
            <Wand2 className={`w-4 h-4 ${isLoading ? "animate-spin" : "animate-bounce"}`} />
            <span>Tạo Slide với Morph</span>
          </button>
        </div>
      </div>
    </div>
  );
};

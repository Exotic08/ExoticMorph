"use client";

import React, { useState, useEffect } from "react";
import { Header } from "@/components/Header";
import { PromptInput } from "@/components/PromptInput";
import { QuickPrompts } from "@/components/QuickPrompts";
import { LoadingProgress } from "@/components/LoadingProgress";
import { SlidePreview } from "@/components/SlidePreview";
import { ErrorNotification } from "@/components/ErrorNotification";
import { 
  PromptFormData, 
  GenerationStatus, 
  SlidePreviewData, 
  QuickPrompt 
} from "@/types";
import { 
  generatePresentationPreview, 
  generatePresentationPptx,
  checkBackendHealth 
} from "@/lib/api";
import { Flame, Activity } from "lucide-react";

export default function HomePage() {
  // Quản lý trạng thái
  const [status, setStatus] = useState<GenerationStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [formData, setFormData] = useState<PromptFormData>({
    topic: "",
    slideCount: 5,
    aspectRatio: "16:9",
    style: "Futuristic",
    includeSpeakerNotes: true,
  });
  
  // Dữ liệu xem trước và file PPTX nhị phân
  const [previewData, setPreviewData] = useState<SlidePreviewData | null>(null);
  const [cachedBlob, setCachedBlob] = useState<Blob | null>(null);
  const [downloadFilename, setDownloadFilename] = useState<string>("exoticmorph_presentation.pptx");
  const [backendStatus, setBackendStatus] = useState<{ online: boolean; provider?: string }>({
    online: false,
  });

  // Kiểm tra sức khỏe Backend khi ứng dụng khởi động
  useEffect(() => {
    checkBackendHealth().then((res) => {
      setBackendStatus({ online: res.online, provider: res.provider });
    });
  }, []);

  /**
   * Gọi API Thật sang FastAPI Backend để sinh Slide Preview và tệp PPTX
   */
  const handleSubmit = async () => {
    if (!formData.topic.trim()) return;

    setStatus("generating");
    setErrorMessage(null);
    setCachedBlob(null);

    try {
      // 1. Gọi API sinh Preview JSON
      const previewResult = await generatePresentationPreview(formData);
      setPreviewData(previewResult);

      // 2. Tải song song hoặc chuẩn bị sẵn binary PPTX Blob
      try {
        const pptxResult = await generatePresentationPptx(formData);
        setCachedBlob(pptxResult.blob);
        setDownloadFilename(pptxResult.filename);
      } catch (blobErr) {
        console.warn("Chưa tạo được blob trước, sẽ tạo khi bấm nút tải:", blobErr);
      }

      // 3. Hoàn tất thành công
      setStatus("completed");
    } catch (err: any) {
      console.error("Lỗi khi kết nối FastAPI Backend:", err);
      const msg =
        err?.message ||
        "Không thể kết nối đến máy chủ ExoticMorph Backend. Vui lòng kiểm tra cổng 8000.";
      setErrorMessage(msg);
      setStatus("error");
    }
  };

  /**
   * Xử lý tải file trực tiếp từ nút trong SlidePreview (nếu chưa có cache blob)
   */
  const handleDownloadRequest = async () => {
    try {
      const pptxResult = await generatePresentationPptx(formData);
      setCachedBlob(pptxResult.blob);
      setDownloadFilename(pptxResult.filename);
    } catch (err: any) {
      alert(`Lỗi khi tải file PPTX: ${err.message || err}`);
      throw err;
    }
  };

  /**
   * Chọn prompt gợi ý nhanh
   */
  const handleSelectQuickPrompt = (item: QuickPrompt) => {
    setFormData({
      ...formData,
      topic: item.promptText,
      slideCount: item.recommendedCount,
      style: item.recommendedStyle,
    });
  };

  /**
   * Đặt lại trạng thái ban đầu
   */
  const handleReset = () => {
    setStatus("idle");
    setErrorMessage(null);
    setPreviewData(null);
    setCachedBlob(null);
  };

  /**
   * Sửa lại prompt hiện tại
   */
  const handleEditPrompt = () => {
    setStatus("idle");
    setErrorMessage(null);
  };

  const isGenerating = status === "generating";

  return (
    <div className="min-h-screen flex flex-col justify-between">
      {/* Thanh Header */}
      <Header onReset={handleReset} />

      {/* Vùng nội dung chính */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        {/* ================= TRẠNG THÁI LỖI (ERROR NOTIFICATION) ================= */}
        {status === "error" && errorMessage && (
          <ErrorNotification
            message={errorMessage}
            onRetry={handleSubmit}
            onDismiss={() => setStatus("idle")}
          />
        )}

        {/* ================= TRẠNG THÁI 1: CHƯA TẠO (IDLE) ================= */}
        {(status === "idle" || status === "error") && (
          <div className="space-y-10">
            {/* Hero Section */}
            <div className="text-center max-w-3xl mx-auto space-y-4">
              <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-semibold shadow-sm">
                <Flame className="w-4 h-4 text-pink-400" />
                <span>Next-Gen PowerPoint AI Generator</span>
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                <span className="text-cyan-300 font-normal">Hiệu ứng Morph 60 FPS</span>
                {backendStatus.online && (
                  <>
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span className="text-emerald-400 font-normal flex items-center gap-1">
                      <Activity className="w-3 h-3" /> Backend Online
                    </span>
                  </>
                )}
              </div>

              <h1 className="text-3xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-white leading-tight">
                Tạo Slide PowerPoint có{" "}
                <span className="text-gradient-morph">Hiệu Ứng Morph</span> bằng AI
              </h1>

              <p className="text-sm sm:text-base text-slate-400 max-w-2xl mx-auto leading-relaxed">
                Biến bất kỳ ý tưởng hoặc dàn ý thành bài thuyết trình PowerPoint chuẩn chuyên nghiệp. 
                AI tự động tính toán tọa độ vector và cấu hình hiệu ứng chuyển cảnh Morphing mượt mà như Apple Keynote.
              </p>
            </div>

            {/* Khung nhập Prompt chính */}
            <PromptInput
              formData={formData}
              onChange={setFormData}
              onSubmit={handleSubmit}
              isLoading={isGenerating}
            />

            {/* Danh sách Prompt gợi ý mẫu */}
            <QuickPrompts onSelectPrompt={handleSelectQuickPrompt} />

            {/* Banner tính năng nổi bật */}
            <div className="pt-8 border-t border-white/[0.06] grid grid-cols-2 md:grid-cols-4 gap-4 max-w-4xl mx-auto text-center">
              <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                <div className="text-purple-400 font-bold text-lg mb-0.5">100% Tự Động</div>
                <div className="text-slate-400 text-xs">Không cần chỉnh tay từng shape</div>
              </div>
              <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                <div className="text-cyan-400 font-bold text-lg mb-0.5">Tệp Chuẩn .pptx</div>
                <div className="text-slate-400 text-xs">Mở được trên Office & WPS</div>
              </div>
              <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                <div className="text-pink-400 font-bold text-lg mb-0.5">Morph Vectors</div>
                <div className="text-slate-400 text-xs">Ánh xạ tọa độ không vỡ hình</div>
              </div>
              <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                <div className="text-emerald-400 font-bold text-lg mb-0.5">Export Cực Nhanh</div>
                <div className="text-slate-400 text-xs">Sẵn sàng trong ~3 giây</div>
              </div>
            </div>
          </div>
        )}

        {/* ================= TRẠNG THÁI 2: ĐANG XỬ LÝ (GENERATING / LOADING) ================= */}
        {status === "generating" && (
          <div>
            <LoadingProgress />
          </div>
        )}

        {/* ================= TRẠNG THÁI 3: HOÀN THÀNH (RESULT PREVIEW) ================= */}
        {status === "completed" && previewData && (
          <div>
            <SlidePreview
              data={previewData}
              cachedBlob={cachedBlob}
              downloadFilename={downloadFilename}
              onReset={handleReset}
              onEditPrompt={handleEditPrompt}
              onDownloadRequest={handleDownloadRequest}
            />
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="w-full border-t border-white/[0.06] bg-[#07080C]/80 py-6 text-center text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-400">ExoticMorph AI</span>
            <span>&bull;</span>
            <span>PowerPoint Morph Automation Engine</span>
          </div>

          <div className="flex items-center gap-4 text-slate-400">
            <span>Powered by Generative AI & OpenXML Morph Compiler</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

"use client";

import React, { useState, useEffect, useCallback } from "react";
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
  QuickPrompt,
  BackendPresentation,
  BackendHealthStatus,
} from "@/types";
import {
  generatePresentationPreview,
  buildPptxFromPresentation,
  generatePresentationPptx,
  checkBackendHealth,
  toErrorMessage,
  type GeneratePptxResult,
} from "@/lib/api";
import { downloadBlob } from "@/lib/download";
import { Flame, Activity } from "lucide-react";

export default function HomePage() {
  // Quản lý trạng thái
  const [status, setStatus] = useState<GenerationStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [formData, setFormData] = useState<PromptFormData>({
    topic: "",
    slideCount: 5,
    aspectRatio: "16:9",
    style: "AUTO",
    includeSpeakerNotes: true,
  });

  // Dữ liệu xem trước và file PPTX nhị phân
  const [previewData, setPreviewData] = useState<SlidePreviewData | null>(null);
  // JSON gốc từ backend — dùng để biên dịch lại .pptx mà KHÔNG gọi LLM lần 2.
  const [sourcePresentation, setSourcePresentation] = useState<BackendPresentation | null>(null);
  const [cachedBlob, setCachedBlob] = useState<Blob | null>(null);
  const [downloadFilename, setDownloadFilename] = useState<string>("exoticmorph_presentation.pptx");
  const [backendStatus, setBackendStatus] = useState<BackendHealthStatus>({
    online: false,
  });

  // Kiểm tra sức khỏe Backend khi ứng dụng khởi động.
  // Cờ `cancelled` chống setState sau khi component unmount.
  useEffect(() => {
    let cancelled = false;
    checkBackendHealth()
      .then((res) => {
        if (!cancelled) setBackendStatus(res);
      })
      .catch(() => {
        if (!cancelled) setBackendStatus({ online: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /**
   * Gọi API Backend để sinh Slide Preview và tệp PPTX.
   *
   * Luồng tối ưu (đợt rework): LLM chỉ được gọi MỘT LẦN qua /generate-json;
   * file .pptx được biên dịch từ chính JSON đó qua /build-pptx => file tải về
   * luôn khớp 100% với Preview. Bản cũ gọi LLM 2 lần (generate-json rồi generate)
   * nên preview và file có thể khác nhau do temperature > 0.
   */
  const handleSubmit = useCallback(async () => {
    if (formData.topic.trim().length < 3) return;

    setStatus("generating");
    setErrorMessage(null);
    setDownloadError(null);
    setCachedBlob(null);
    setSourcePresentation(null);

    try {
      // 1. Gọi LLM sinh cấu trúc JSON (lần duy nhất)
      const { preview, source } = await generatePresentationPreview(formData);
      setPreviewData(preview);
      setSourcePresentation(source);

      // 2. Biên dịch file PPTX từ JSON vừa có (không tốn thêm lượt gọi LLM).
      //    Nếu bước này fail thì Preview vẫn dùng được — nút tải sẽ thử lại.
      try {
        const pptxResult = await buildPptxFromPresentation(source);
        setCachedBlob(pptxResult.blob);
        setDownloadFilename(pptxResult.filename);
      } catch (blobErr) {
        console.warn("Chưa tạo được blob PPTX, sẽ thử lại khi người dùng bấm tải:", blobErr);
      }

      // 3. Hoàn tất thành công
      setStatus("completed");
    } catch (err: unknown) {
      console.error("Lỗi khi kết nối FastAPI Backend:", err);
      setErrorMessage(
        toErrorMessage(
          err,
          "Không thể kết nối đến máy chủ ExoticMorph Backend. Vui lòng kiểm tra lại kết nối."
        )
      );
      setStatus("error");
    }
  }, [formData]);

  /**
   * Xử lý tải file khi người dùng bấm nút tải mà chưa có blob trong cache.
   *
   * FIX đợt rework: bản cũ fetch blob xong KHÔNG tự kích hoạt download — người
   * dùng phải bấm nút 2 lần mới nhận được file. Giờ file được tải NGAY khi có blob.
   */
  const handleDownloadRequest = useCallback(async (): Promise<void> => {
    setDownloadError(null);
    try {
      let pptxResult: GeneratePptxResult;

      if (sourcePresentation) {
        // Ưu tiên biên dịch từ JSON nguồn (không gọi LLM, kết quả khớp preview)
        try {
          pptxResult = await buildPptxFromPresentation(sourcePresentation);
        } catch (buildErr) {
          // Fallback cuối cùng: endpoint /generate (gọi LLM lại từ đầu)
          console.warn("build-pptx thất bại, chuyển sang /generate:", buildErr);
          pptxResult = await generatePresentationPptx(formData);
        }
      } else {
        pptxResult = await generatePresentationPptx(formData);
      }

      setCachedBlob(pptxResult.blob);
      setDownloadFilename(pptxResult.filename);
      // Kích hoạt tải xuống ngay khi có dữ liệu (không cần bấm nút lần 2)
      downloadBlob(pptxResult.blob, pptxResult.filename);
    } catch (err: unknown) {
      const message = toErrorMessage(err, "Không thể tải file PPTX. Vui lòng thử lại!");
      setDownloadError(message);
      // Re-throw để SlidePreview biết là đã fail và không hiển thị "Đã tải về"
      throw err instanceof Error ? err : new Error(message);
    }
  }, [formData, sourcePresentation]);

  /**
   * Chọn prompt gợi ý nhanh
   */
  const handleSelectQuickPrompt = useCallback((item: QuickPrompt) => {
    setFormData((prev) => ({
      ...prev,
      topic: item.promptText,
      slideCount: item.recommendedCount,
      style: "AUTO",
    }));
  }, []);

  /**
   * Đặt lại trạng thái ban đầu
   */
  const handleReset = useCallback(() => {
    setStatus("idle");
    setErrorMessage(null);
    setDownloadError(null);
    setPreviewData(null);
    setSourcePresentation(null);
    setCachedBlob(null);
  }, []);

  /**
   * Sửa lại prompt hiện tại
   */
  const handleEditPrompt = useCallback(() => {
    setStatus("idle");
    setErrorMessage(null);
    setDownloadError(null);
  }, []);

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

        {/* Lỗi riêng của luồng tải file (hiện khi đang ở màn hình kết quả) */}
        {status === "completed" && downloadError && (
          <ErrorNotification
            message={downloadError}
            onRetry={() => void handleDownloadRequest()}
            onDismiss={() => setDownloadError(null)}
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
              onError={setDownloadError}
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

/**
 * API Client Layer for ExoticMorph
 * ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 * Quản lý các cuộc gọi HTTP kết nối giữa Next.js Frontend và FastAPI Backend.
 */

import { PromptFormData, SlidePreviewData, SlideItem } from "@/types";
import { extractFilenameFromDisposition } from "./download";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface GeneratePptxResult {
  blob: Blob;
  filename: string;
  slideCount: number;
  style: string;
}

/**
 * Interface cho JSON trả về từ backend endpoint /api/v1/generate-json
 */
interface BackendSlideElement {
  id: string;
  type: string;
  content: string;
  label?: string | null;
  sub_text?: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  bg_color?: string;
  text_color?: string;
  morph_id: string;
  font_size?: number | null;
}

interface BackendSlide {
  slide_number: number;
  title: string;
  subtitle?: string | null;
  morph_description?: string | null;
  bg_color?: string;
  elements: BackendSlideElement[];
}

interface BackendPresentationResponse {
  topic: string;
  style: "Futuristic" | "Minimal" | "Corporate" | "Creative";
  aspect_ratio: "16:9" | "4:3";
  total_slides: number;
  slides: BackendSlide[];
  morph_strategy?: string | null;
}

/**
 * Kiểm tra trạng thái hoạt động của Backend
 */
export async function checkBackendHealth(): Promise<{
  online: boolean;
  provider?: string;
  version?: string;
}> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);

    const res = await fetch(`${API_BASE_URL}/api/v1/health`, {
      method: "GET",
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json();
      return {
        online: true,
        provider: data.llm_provider,
        version: data.version,
      };
    }
    return { online: false };
  } catch {
    return { online: false };
  }
}

/**
 * Gọi API /api/v1/generate-json để lấy cấu trúc dữ liệu bài trình chiếu (Dành cho Slide Preview)
 */
export async function generatePresentationPreview(
  formData: PromptFormData
): Promise<SlidePreviewData> {
  const payload = {
    prompt: formData.topic,
    num_slides: formData.slideCount,
    style: formData.style,
    aspect_ratio: formData.aspectRatio,
    language: "vi",
  };

  const response = await fetch(`${API_BASE_URL}/api/v1/generate-json`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let errorDetail = "Lỗi khi giao tiếp với máy chủ AI Backend.";
    try {
      const errorJson = await response.json();
      errorDetail = errorJson.detail || errorJson.message || errorDetail;
    } catch {
      // Ignored if not json
    }
    throw new Error(`[HTTP ${response.status}] ${errorDetail}`);
  }

  const data: BackendPresentationResponse = await response.json();

  // Chuyển đổi dữ liệu Backend sang định dạng SlidePreviewData của Frontend
  const mappedSlides: SlideItem[] = data.slides.map((s, idx) => {
    // Tách các metrics nếu có
    const metrics = s.elements
      .filter((e) => e.type === "metric")
      .map((m) => ({
        label: m.label || "Chỉ số",
        value: m.content,
        change: m.sub_text || undefined,
        isPositive: true,
      }));

    // Tách bullet points nếu có dạng card
    const bulletPoints = s.elements
      .filter((e) => e.type === "card" || e.type === "text")
      .map((c) => (c.label ? `[${c.label}] ${c.content}` : c.content));

    return {
      id: idx + 1,
      slideNumber: s.slide_number,
      title: s.title,
      subtitle: s.subtitle || undefined,
      badge: `Slide 0${s.slide_number}`,
      bulletPoints: bulletPoints.length > 0 ? bulletPoints : undefined,
      metrics: metrics.length > 0 ? metrics : undefined,
      layoutType: idx === 0 ? "title-hero" : metrics.length > 0 ? "metrics-grid" : "split-feature",
      morphDescription:
        s.morph_description ||
        `Tự động nội suy các hình khối có cùng Morph ID sang Slide ${idx + 1}`,
      morphAnchors: s.elements.map((e) => ({
        id: e.morph_id,
        name: `Anchor: !!${e.morph_id}`,
        transitionType: "translate",
      })),
      speakerNotes: `Lời dẫn slide ${s.slide_number}: Trình bày chi tiết về ${s.title}...`,
      tags: [data.style, `Slide-${s.slide_number}`],
    };
  });

  return {
    presentationTitle: data.topic.split("\n")[0].slice(0, 50) || "Bản Trình Chiếu ExoticMorph",
    presentationSubtitle: `Tạo bởi AI (${data.style} Style) • ${data.aspect_ratio}`,
    totalSlides: data.total_slides,
    aspectRatio: data.aspect_ratio,
    style: data.style,
    generatedAt: new Date().toLocaleTimeString("vi-VN"),
    fileSizeEstimate: `${(data.total_slides * 0.85).toFixed(1)} MB`,
    morphTransitionsCount: Math.max(0, data.total_slides - 1),
    slides: mappedSlides,
    morphHighlights: [
      "Tự động đồng bộ tiền tố (!!) cho các đối tượng Morph",
      "Bảo toàn tọa độ vector hình học không bị méo hình",
      "Kích hoạt thẻ OpenXML <p:transition><p:morph/></p:transition>",
    ],
  };
}

/**
 * Gọi API /api/v1/generate để tải trực tiếp file nhị phân .pptx về client
 */
export async function generatePresentationPptx(
  formData: PromptFormData
): Promise<GeneratePptxResult> {
  const payload = {
    prompt: formData.topic,
    num_slides: formData.slideCount,
    style: formData.style,
    aspect_ratio: formData.aspectRatio,
    language: "vi",
  };

  const response = await fetch(`${API_BASE_URL}/api/v1/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let errorDetail = "Không thể tạo file PowerPoint (.pptx).";
    try {
      const errorJson = await response.json();
      errorDetail = errorJson.detail || errorJson.message || errorDetail;
    } catch {
      // Ignored if not json
    }
    throw new Error(`[HTTP ${response.status}] ${errorDetail}`);
  }

  // Đọc dữ liệu nhị phân Blob
  const blob = await response.blob();

  // Trích xuất tên file từ header Content-Disposition
  const contentDisposition = response.headers.get("Content-Disposition");
  const filename = extractFilenameFromDisposition(
    contentDisposition,
    "exoticmorph_presentation.pptx"
  );

  const slideCountHeader = response.headers.get("X-Slide-Count");
  const slideCount = slideCountHeader ? parseInt(slideCountHeader, 10) : formData.slideCount;
  const style = response.headers.get("X-Morph-Style") || formData.style;

  return {
    blob,
    filename,
    slideCount,
    style,
  };
}

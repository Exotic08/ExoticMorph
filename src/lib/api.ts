/**
 * API Client Layer for ExoticMorph
 * ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 * Quản lý các cuộc gọi HTTP kết nối giữa Next.js Frontend và FastAPI Backend.
 *
 * Nâng cấp trong đợt rework:
 * - Mọi request đều có TIMEOUT (AbortController) -> UI không bao giờ kẹt vĩnh
 *   viễn ở trạng thái Loading khi Backend chết / Render cold-start quá lâu.
 * - Lớp lỗi có kiểu (ApiError) thay vì bắt `any` -> thông báo thân thiện tiếng Việt.
 * - `generatePresentationPreview` trả về kèm JSON gốc của backend để tái sử dụng
 *   cho /build-pptx: LLM chỉ được gọi MỘT LẦN, file tải về luôn khớp Preview
 *   (bản cũ gọi LLM 2 lần với temperature 0.7, 2 kết quả có thể khác nhau).
 * - clearTimeout luôn chạy trong finally (bản cũ leak timer khi fetch throw).
 */

import {
  BackendHealthResponse,
  BackendHealthStatus,
  BackendPresentation,
  PromptFormData,
  SlideItem,
  SlidePreviewData,
} from "@/types";
import { extractFilenameFromDisposition } from "./download";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Budget thời gian chờ (ms) cho từng loại request:
 * - Health check ngắn (chỉ dò badge trạng thái, không chặn UI).
 * - Sinh preview phải đủ dài: Render free-tier cold-start 30-50s + LLM có thể
 *   retry 3 lần với backoff.
 */
const HEALTH_TIMEOUT_MS = 5_000;
const PREVIEW_TIMEOUT_MS = 240_000;
const BINARY_TIMEOUT_MS = 180_000;

/** MIME type chuẩn của file .pptx (OpenXML PresentationML) */
const PPTX_MIME_TYPE =
  "application/vnd.openxmlformats-officedocument.presentationml.presentation";

export interface GeneratePptxResult {
  blob: Blob;
  filename: string;
  slideCount: number;
  style: string;
}

/** Kết quả của lượt sinh preview: kèm JSON gốc để build file deterministic */
export interface PreviewGenerationResult {
  preview: SlidePreviewData;
  /** JSON backend gốc — POST ngược lên /api/v1/build-pptx để lấy file .pptx */
  source: BackendPresentation;
}

/** Phân loại lỗi để hiển thị thông báo phù hợp cho người dùng cuối */
export type ApiErrorKind = "timeout" | "network" | "http" | "parse";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

/**
 * Chuyển bất kỳ exception nào (unknown) thành message thân thiện.
 * Thay thế hoàn toàn các khối `catch (err: any)` vi phạm strict mode.
 */
export function toErrorMessage(err: unknown, fallback = "Đã xảy ra lỗi không xác định."): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

/**
 * fetch kèm timeout bằng AbortController.
 * Timer luôn được giải phóng trong finally kể cả khi fetch ném exception
 * (bản cũ chỉ clearTimeout trên đường thành công -> leak timer).
 */
async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err) {
    // AbortError = hết timeout, các lỗi khác = mất kết nối/DNS...
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(
        "timeout",
        `⏱ Máy chủ phản hồi quá chậm (quá ${Math.round(timeoutMs / 1000)}s). ` +
          "Backend free-tier có thể đang cold-start — vui lòng thử lại sau ít giây."
      );
    }
    throw new ApiError(
      "network",
      "Không thể kết nối đến máy chủ ExoticMorph Backend. " +
        "Vui lòng kiểm tra kết nối mạng hoặc trạng thái Backend."
    );
  } finally {
    clearTimeout(timer);
  }
}

/** Đọc message lỗi từ body JSON của FastAPI (HTTPException.detail) */
async function readHttpErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === "string" && detail.trim()) return detail;
    }
  } catch {
    // Body không phải JSON (vd: gateway timeout HTML) -> dùng fallback
  }
  return fallback;
}

/**
 * Kiểm tra trạng thái hoạt động của Backend (badge "Backend Online").
 * Không bao giờ throw — luôn trả trạng thái offline khi có sự cố.
 */
export async function checkBackendHealth(): Promise<BackendHealthStatus> {
  try {
    const res = await fetchWithTimeout(
      `${API_BASE_URL}/api/v1/health`,
      { method: "GET", cache: "no-store" },
      HEALTH_TIMEOUT_MS
    );
    if (res.ok) {
      const data = (await res.json()) as Partial<BackendHealthResponse>;
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

/** Payload gửi lên các endpoint sinh slide của backend */
function buildGeneratePayload(formData: PromptFormData) {
  return {
    prompt: formData.topic.trim(),
    num_slides: formData.slideCount,
    style: formData.style,
    aspect_ratio: formData.aspectRatio,
    language: "vi",
    include_speaker_notes: formData.includeSpeakerNotes ?? true,
  };
}

/**
 * Gọi API /api/v1/generate-json để lấy cấu trúc dữ liệu bài trình chiếu
 * (Dành cho Slide Preview). Trả về kèm JSON gốc để dùng cho /build-pptx.
 */
export async function generatePresentationPreview(
  formData: PromptFormData
): Promise<PreviewGenerationResult> {
  const response = await fetchWithTimeout(
    `${API_BASE_URL}/api/v1/generate-json`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(buildGeneratePayload(formData)),
    },
    PREVIEW_TIMEOUT_MS
  );

  if (!response.ok) {
    const errorDetail = await readHttpErrorMessage(
      response,
      "Lỗi khi giao tiếp với máy chủ AI Backend."
    );
    throw new ApiError("http", `[HTTP ${response.status}] ${errorDetail}`, response.status);
  }

  let data: BackendPresentation;
  try {
    data = (await response.json()) as BackendPresentation;
  } catch {
    throw new ApiError("parse", "Dữ liệu trả về từ Backend không đúng định dạng JSON.");
  }

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
        transitionType: "translate" as const,
      })),
      // Ưu tiên speaker notes THẬT từ backend; chỉ tự sinh câu chào khi backend không có.
      speakerNotes:
        s.speaker_notes?.trim() ||
        `Lời dẫn slide ${s.slide_number}: Trình bày chi tiết về ${s.title}...`,
      tags: [data.style, `Slide-${s.slide_number}`],
    };
  });

  const preview: SlidePreviewData = {
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

  return { preview, source: data };
}

/**
 * Parse response binary .pptx thành Blob + tên file + metadata header.
 */
async function parsePptxResponse(
  response: Response,
  fallbackSlideCount: number,
  fallbackStyle: string
): Promise<GeneratePptxResult> {
  const blob = await response.blob();

  const contentDisposition = response.headers.get("Content-Disposition");
  const filename = extractFilenameFromDisposition(
    contentDisposition,
    "exoticmorph_presentation.pptx"
  );

  const slideCountHeader = response.headers.get("X-Slide-Count");
  const parsedSlideCount = slideCountHeader ? Number.parseInt(slideCountHeader, 10) : NaN;
  // parseInt có thể trả NaN (header rác) -> fallback về số slide của form.
  const slideCount = Number.isFinite(parsedSlideCount) && parsedSlideCount > 0
    ? parsedSlideCount
    : fallbackSlideCount;

  return {
    blob,
    filename,
    slideCount,
    style: response.headers.get("X-Morph-Style") || fallbackStyle,
  };
}

/**
 * Biên dịch file .pptx từ JSON PresentationResponse có sẵn (endpoint /api/v1/build-pptx).
 * KHÔNG gọi LLM -> nhanh, rẻ, và file luôn khớp 100% với Preview đang hiển thị.
 */
export async function buildPptxFromPresentation(
  source: BackendPresentation
): Promise<GeneratePptxResult> {
  const response = await fetchWithTimeout(
    `${API_BASE_URL}/api/v1/build-pptx`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: PPTX_MIME_TYPE,
      },
      body: JSON.stringify(source),
    },
    BINARY_TIMEOUT_MS
  );

  if (!response.ok) {
    const errorDetail = await readHttpErrorMessage(
      response,
      "Không thể biên dịch file PowerPoint (.pptx)."
    );
    throw new ApiError("http", `[HTTP ${response.status}] ${errorDetail}`, response.status);
  }

  return parsePptxResponse(response, source.total_slides, source.style);
}

/**
 * Gọi API /api/v1/generate để tải trực tiếp file nhị phân .pptx về client.
 * Chỉ dùng làm đường dự phòng khi không còn JSON nguồn (goi LLM lần nữa).
 */
export async function generatePresentationPptx(
  formData: PromptFormData
): Promise<GeneratePptxResult> {
  const response = await fetchWithTimeout(
    `${API_BASE_URL}/api/v1/generate`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: PPTX_MIME_TYPE,
      },
      body: JSON.stringify(buildGeneratePayload(formData)),
    },
    BINARY_TIMEOUT_MS
  );

  if (!response.ok) {
    const errorDetail = await readHttpErrorMessage(
      response,
      "Không thể tạo file PowerPoint (.pptx)."
    );
    throw new ApiError("http", `[HTTP ${response.status}] ${errorDetail}`, response.status);
  }

  return parsePptxResponse(response, formData.slideCount, formData.style);
}

export { API_BASE_URL };

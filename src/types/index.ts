/**
 * Types & Interfaces for ExoticMorph AI Presentation Generator
 */

export type SlideCountOption = 3 | 5 | 10;
export type AspectRatioOption = "16:9" | "4:3";
export type SlideStyleOption = "Minimal" | "Futuristic" | "Corporate" | "Creative";

/**
 * Shape của JSON trả về TRỰC TIẾP từ FastAPI Backend (giữ nguyên snake_case).
 * Dùng cho cả việc parse response và gửi ngược lên /api/v1/build-pptx.
 */
export interface BackendSlideElement {
  id: string;
  type:
    | "text"
    | "shape"
    | "card"
    | "metric"
    | "heading"
    | "badge"
    | "kicker"
    | "footer"
    | "connector"
    | "accent";
  content: string;
  label?: string | null;
  sub_text?: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  bg_color?: string | null;
  text_color?: string | null;
  morph_id: string;
  font_size?: number | null;
  shape_type?: string | null;
  border_color?: string | null;
  accent_color?: string | null;
  step?: number | null;
  align?: "left" | "center" | "right" | null;
}

export interface BackendSlide {
  slide_number: number;
  title: string;
  section?: string;
  subtitle?: string | null;
  speaker_notes?: string | null;
  morph_description?: string | null;
  bg_color?: string | null;
  layout_type?: "hero" | "compare" | "features" | "roadmap" | "grid";
  elements: BackendSlideElement[];
}

export interface BackendPresentation {
  topic: string;
  style: SlideStyleOption;
  aspect_ratio: AspectRatioOption;
  total_slides: number;
  slides: BackendSlide[];
  morph_strategy?: string | null;
}

/** Kết quả health check từ /api/v1/health */
export interface BackendHealthResponse {
  status: string;
  service: string;
  version: string;
  llm_provider: string;
  openai_configured?: boolean;
  gemini_configured?: boolean;
}

export interface BackendHealthStatus {
  online: boolean;
  provider?: string;
  version?: string;
}

/**
 * Form data collected from user input
 */
export interface PromptFormData {
  topic: string;
  slideCount: SlideCountOption;
  aspectRatio: AspectRatioOption;
  style: SlideStyleOption;
  includeSpeakerNotes?: boolean;
}

/**
 * Visual element types supported on slide preview
 */
export type VisualElementType = "metrics" | "chart" | "diagram" | "cards" | "quote" | "timeline";

export interface MetricItem {
  label: string;
  value: string;
  change?: string;
  isPositive?: boolean;
}

/** Một thẻ nội dung hai phần: thông điệp cụ thể + đoạn diễn giải chi tiết. */
export interface PreviewCard {
  title: string;
  body: string;
  accentColor?: string;
  step?: number;
}

export interface MorphAnchor {
  id: string;
  name: string;
  fromCoords?: { x: number; y: number; w: number; h: number };
  toCoords?: { x: number; y: number; w: number; h: number };
  transitionType: "scale" | "translate" | "fade-transform" | "reorganize";
}

/**
 * Individual Slide Content structure
 */
export interface SlideItem {
  id: number;
  slideNumber: number;
  title: string;
  subtitle?: string;
  badge?: string;
  section?: string;
  bulletPoints?: string[];
  cards?: PreviewCard[];
  layoutType: "title-hero" | "split-feature" | "metrics-grid" | "timeline-step" | "cards-compare" | "conclusion";
  morphDescription: string;
  morphAnchors: MorphAnchor[];
  metrics?: MetricItem[];
  tags?: string[];
  speakerNotes?: string;
}

/**
 * Generated Presentation Preview Result
 */
export interface SlidePreviewData {
  presentationTitle: string;
  presentationSubtitle: string;
  totalSlides: number;
  aspectRatio: AspectRatioOption;
  style: SlideStyleOption;
  generatedAt: string;
  fileSizeEstimate: string;
  morphTransitionsCount: number;
  slides: SlideItem[];
  morphHighlights: string[];
}

/**
 * Generation workflow status
 */
export type GenerationStatus = "idle" | "generating" | "completed" | "error";

/**
 * Progress step during AI Morph generation
 */
export interface GenerationProgressStep {
  id: string;
  label: string;
  detail: string;
  progressPercentage: number;
  completed: boolean;
  current: boolean;
}

/**
 * Quick prompt template suggestion
 */
export interface QuickPrompt {
  id: string;
  title: string;
  category: "Pitch Deck" | "Báo cáo Kinh doanh" | "Tech Keynote" | "Đào tạo & Giáo dục";
  badge: string;
  icon: string;
  description: string;
  promptText: string;
  recommendedCount: SlideCountOption;
  recommendedStyle: SlideStyleOption;
}

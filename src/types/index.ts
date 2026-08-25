/**
 * Types & Interfaces for ExoticMorph AI Presentation Generator
 */

export type SlideCountOption = 3 | 5 | 10;
export type AspectRatioOption = "16:9" | "4:3";
export type SlideStyleOption = "Minimal" | "Futuristic" | "Corporate" | "Creative";

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
  bulletPoints?: string[];
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

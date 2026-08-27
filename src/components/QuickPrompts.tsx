"use client";

import React from "react";
import { 
  Rocket, 
  TrendingUp, 
  Cpu, 
  GraduationCap, 
  Sparkles,
  ArrowUpRight
} from "lucide-react";
import { QuickPrompt } from "@/types";

interface QuickPromptsProps {
  onSelectPrompt: (prompt: QuickPrompt) => void;
}

export const SAMPLE_PROMPTS: QuickPrompt[] = [
  {
    id: "pitch-deck-ai",
    title: "Pitch Deck Startup AI & SaaS",
    category: "Pitch Deck",
    badge: "Phổ biến nhất",
    icon: "Rocket",
    description: "Slide gọi vốn Seed/Series A: Vấn đề thị trường, Giải pháp AI, Traction và Lộ trình phát triển sản phẩm.",
    promptText: "Tạo bài thuyết trình Pitch Deck gọi vốn 1 triệu USD cho startup 'NexusAI' - Nền tảng tự động hóa quy trình CSKH doanh nghiệp bằng Generative AI. Cần nêu rõ Problem, Solution, Market Size (TAM $50B), Business Model, Traction 2024 và kế hoạch giải ngân vốn.",
    recommendedCount: 5,
  },
  {
    id: "quarterly-growth",
    title: "Báo Cáo Tăng Trưởng Kinh Doanh Q3",
    category: "Báo cáo Kinh doanh",
    badge: "Doanh nghiệp",
    icon: "TrendingUp",
    description: "Tổng hợp doanh thu, biểu đồ tỷ lệ giữ chân khách hàng (Retention), CAC, LTV và mục tiêu Q4.",
    promptText: "Báo cáo kết quả kinh doanh quý 3/2024 của công ty E-Commerce: Doanh thu đạt 12.5 triệu USD (+35% QoQ), Tỷ lệ chuyển đổi tăng từ 2.8% lên 4.2%, Chi phí CAC giảm 18%. Đưa ra 3 chiến lược mũi nhọn cho mùa mua sắm cuối năm Q4.",
    recommendedCount: 5,
  },
  {
    id: "system-architecture",
    title: "Kiến Trúc Hệ Thống Cloud & Microservices",
    category: "Tech Keynote",
    badge: "Kỹ thuật",
    icon: "Cpu",
    description: "Minh họa dòng dữ liệu từ API Gateway sang K8s clusters, Kafka queue và Database Sharding với hiệu ứng Morph.",
    promptText: "Trình bày kiến trúc kỹ thuật hệ thống FinTech xử lý 100,000 TPS: Giải thích luồng dữ liệu đi qua Cloudflare Edge, API Gateway, Event Mesh Kafka, Microservices Go/Rust và CockroachDB đa vùng. Nhấn mạnh tính chịu lỗi High Availability 99.999%.",
    recommendedCount: 3,
  },
  {
    id: "ai-transformation-masterclass",
    title: "Chiến Lược Chuyển Đổi Số Với AI",
    category: "Đào tạo & Giáo dục",
    badge: "Chiến lược",
    icon: "GraduationCap",
    description: "Khung năng lực số, lộ trình đào tạo nhân sự và áp dụng AI Agent vào chuỗi giá trị doanh nghiệp.",
    promptText: "Bài giảng chuyên sâu dành cho ban lãnh đạo về 'Chiến lược ứng dụng AI vào doanh nghiệp 2025-2030'. Phân tích 4 trụ cột: Văn hóa đổi mới, Hạ tầng dữ liệu, Ứng dụng Agentic AI và Quản trị rủi ro AI Ethics.",
    recommendedCount: 10,
  },
];

export const QuickPrompts: React.FC<QuickPromptsProps> = ({ onSelectPrompt }) => {
  const getIcon = (iconName: string) => {
    switch (iconName) {
      case "Rocket":
        return <Rocket className="w-4 h-4 text-pink-400" />;
      case "TrendingUp":
        return <TrendingUp className="w-4 h-4 text-emerald-400" />;
      case "Cpu":
        return <Cpu className="w-4 h-4 text-cyan-400" />;
      case "GraduationCap":
        return <GraduationCap className="w-4 h-4 text-purple-400" />;
      default:
        return <Sparkles className="w-4 h-4 text-purple-400" />;
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto mt-6">
      <div className="flex items-center justify-between mb-3 px-1">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-semibold text-slate-300">
            Prompt mẫu gợi ý (Quick Prompts)
          </h3>
        </div>
        <span className="text-xs text-slate-500">
          Nhấp để tự động điền nội dung
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {SAMPLE_PROMPTS.map((item) => (
          <button
            key={item.id}
            onClick={() => onSelectPrompt(item)}
            className="group text-left p-4 rounded-xl glass-card glass-card-hover relative overflow-hidden focus:outline-none focus:ring-2 focus:ring-purple-500/50"
          >
            {/* Top row */}
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-white/[0.05] border border-white/[0.08] group-hover:bg-purple-500/10 group-hover:border-purple-500/30 transition-colors">
                  {getIcon(item.icon)}
                </div>
                <span className="text-xs font-medium text-slate-400 group-hover:text-purple-300 transition-colors">
                  {item.category}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-white/[0.04] text-slate-400 border border-white/[0.06]">
                  {item.badge}
                </span>
                <ArrowUpRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-purple-400 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all" />
              </div>
            </div>

            {/* Title & Desc */}
            <h4 className="text-sm font-semibold text-slate-100 group-hover:text-purple-200 transition-colors line-clamp-1 mb-1">
              {item.title}
            </h4>
            <p className="text-xs text-slate-400 line-clamp-2 leading-relaxed">
              {item.description}
            </p>

            {/* Config pills */}
            <div className="mt-3 pt-2 border-t border-white/[0.04] flex items-center gap-2 text-[10px] text-slate-400">
              <span className="bg-purple-500/10 text-purple-300 px-2 py-0.5 rounded">
                {item.recommendedCount} Slides
              </span>
              <span className="bg-cyan-500/10 text-cyan-300 px-2 py-0.5 rounded">
                AI chọn style
              </span>
              <span className="text-slate-500 ml-auto group-hover:text-slate-300 transition-colors">
                Thử ngay &rarr;
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};

"use client";

import React from "react";
import { Sparkles, Github, BookOpen, Layers, Presentation } from "lucide-react";

interface HeaderProps {
  onReset?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onReset }) => {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-white/[0.08] bg-[#090A0F]/80 backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand Logo & Tagline */}
        <div 
          onClick={onReset}
          className="flex items-center gap-3 cursor-pointer group select-none"
        >
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 via-purple-600 to-pink-500 p-[1px] shadow-lg shadow-purple-500/20 group-hover:shadow-purple-500/40 transition-all duration-300">
            <div className="w-full h-full bg-[#0E1017] rounded-[11px] flex items-center justify-center">
              <Layers className="w-5 h-5 text-purple-400 group-hover:scale-110 group-hover:text-pink-300 transition-transform duration-300" />
            </div>
            {/* Morph dot pulse */}
            <span className="absolute -top-1 -right-1 flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-cyan-500"></span>
            </span>
          </div>

          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="text-xl font-bold tracking-tight text-white font-sans">
                Exotic<span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 via-pink-400 to-cyan-400">Morph</span>
              </span>
              <span className="hidden sm:inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-purple-500/10 text-purple-300 border border-purple-500/30">
                v1.0 Beta
              </span>
            </div>
            <span className="text-[11px] text-slate-400 hidden md:block">
              AI PowerPoint Morph Generator
            </span>
          </div>
        </div>

        {/* Center Pill Badge - USP */}
        <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/[0.03] border border-white/[0.08] text-xs text-slate-300">
          <Sparkles className="w-3.5 h-3.5 text-yellow-400 animate-pulse" />
          <span>Tự động khớp tọa độ & biến đổi hình dạng Morph mượt mà</span>
        </div>

        {/* Navigation & Action Links */}
        <div className="flex items-center gap-3">
          <a
            href="https://github.com/Exotic08/ExoticMorph"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs font-medium text-slate-300 hover:text-white px-3 py-1.5 rounded-lg hover:bg-white/[0.06] transition-colors border border-transparent hover:border-white/[0.08]"
          >
            <Github className="w-4 h-4" />
            <span className="hidden sm:inline">GitHub</span>
          </a>

          <a
            href="#docs"
            onClick={(e) => {
              e.preventDefault();
              alert("Tài liệu hướng dẫn hiệu ứng Morph PPTX đang được cập nhật!");
            }}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-300 hover:text-white px-3 py-1.5 rounded-lg hover:bg-white/[0.06] transition-colors border border-transparent hover:border-white/[0.08]"
          >
            <BookOpen className="w-4 h-4" />
            <span className="hidden sm:inline">Tài liệu</span>
          </a>

          <button
            onClick={onReset}
            className="flex items-center gap-1.5 text-xs font-semibold text-purple-300 hover:text-purple-100 px-3.5 py-1.5 rounded-lg bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/30 transition-all shadow-sm"
          >
            <Presentation className="w-4 h-4" />
            <span>Tạo mới</span>
          </button>
        </div>
      </div>
    </header>
  );
};

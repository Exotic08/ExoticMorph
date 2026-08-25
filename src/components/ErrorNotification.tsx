"use client";

import React from "react";
import { AlertTriangle, RefreshCw, X, ServerCrash } from "lucide-react";

interface ErrorNotificationProps {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export const ErrorNotification: React.FC<ErrorNotificationProps> = ({
  message,
  onRetry,
  onDismiss,
}) => {
  return (
    <div className="w-full max-w-4xl mx-auto my-6 animate-fadeIn">
      <div className="relative rounded-2xl bg-rose-950/40 border border-rose-500/40 p-5 backdrop-blur-xl shadow-2xl overflow-hidden">
        {/* Glow ambient accent */}
        <div className="absolute -left-10 -top-10 w-40 h-40 bg-rose-600/20 rounded-full blur-3xl pointer-events-none" />

        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="p-2.5 rounded-xl bg-rose-500/20 text-rose-400 border border-rose-500/30 shrink-0 mt-0.5">
              <ServerCrash className="w-5 h-5" />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-bold text-rose-200">
                  Đã xảy ra lỗi trong quá trình tạo bài thuyết trình
                </h4>
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                  Backend Error
                </span>
              </div>

              <p className="text-xs text-rose-300/90 leading-relaxed font-mono bg-black/30 p-2.5 rounded-lg border border-rose-500/20">
                {message}
              </p>

              <div className="text-[11px] text-slate-400 pt-1">
                Gợi ý: Hãy đảm bảo máy chủ FastAPI Backend đang chạy tại cổng{" "}
                <code className="text-purple-300 font-mono">http://localhost:8000</code>{" "}
                hoặc kiểm tra lại cấu hình API Key trong file <code className="text-purple-300 font-mono">.env</code>.
              </div>
            </div>
          </div>

          {onDismiss && (
            <button
              onClick={onDismiss}
              className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-white/[0.05] transition-colors"
              title="Đóng thông báo"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Action button */}
        {onRetry && (
          <div className="mt-4 pt-3 border-t border-rose-500/20 flex items-center justify-end gap-3">
            <button
              onClick={onRetry}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-white bg-rose-600 hover:bg-rose-500 active:scale-95 transition-all shadow-md flex items-center gap-2"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Thử lại ngay</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ExoticMorph | AI PowerPoint Morph Generator",
  description:
    "Tạo slide thuyết trình PowerPoint chuyên nghiệp với hiệu ứng Morph chuyển động mượt mà hoàn toàn tự động bằng AI.",
  keywords: [
    "AI PowerPoint",
    "PowerPoint Morph",
    "Slide Generator",
    "Presentation AI",
    "Gamma alternative",
    "Tome alternative",
    "ExoticMorph",
  ],
  authors: [{ name: "ExoticMorph Team" }],
};

export const viewport: Viewport = {
  themeColor: "#090A0F",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" className="dark scroll-smooth">
      <body className="min-h-screen bg-[#090A0F] text-slate-100 font-sans selection:bg-purple-500/30 selection:text-purple-200 overflow-x-hidden antialiased">
        {/* Subtle Ambient Background Gradients */}
        <div className="fixed inset-0 pointer-events-none -z-10 overflow-hidden">
          <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-[900px] h-[500px] bg-gradient-to-b from-purple-600/15 via-indigo-500/10 to-transparent blur-[120px] rounded-full" />
          <div className="absolute top-1/3 -left-40 w-[500px] h-[500px] bg-cyan-500/8 blur-[140px] rounded-full" />
          <div className="absolute bottom-10 right-[-100px] w-[600px] h-[600px] bg-pink-500/8 blur-[150px] rounded-full" />
          <div className="absolute inset-0 bg-grid-pattern opacity-40" />
        </div>
        {children}
      </body>
    </html>
  );
}

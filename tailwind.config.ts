import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#090A0F",
        surface: {
          50: "#1E2230",
          100: "#161922",
          200: "#12141C",
          300: "#0D0F15",
          border: "rgba(255, 255, 255, 0.08)",
          hover: "rgba(255, 255, 255, 0.04)",
        },
        brand: {
          purple: "#8B5CF6",
          violet: "#6366F1",
          cyan: "#06B6D4",
          fuchsia: "#D946EF",
          pink: "#EC4899",
          amber: "#F59E0B",
          emerald: "#10B981",
        },
      },
      backgroundImage: {
        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",
        "hero-glow": "radial-gradient(circle at 50% -20%, rgba(139, 92, 246, 0.25), rgba(6, 182, 212, 0.1) 45%, transparent 70%)",
        "card-glow": "radial-gradient(circle at top left, rgba(139, 92, 246, 0.15), transparent 60%)",
        "morph-gradient": "linear-gradient(135deg, #6366F1 0%, #8B5CF6 50%, #EC4899 100%)",
      },
      animation: {
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "float-slow": "float 6s ease-in-out infinite",
        "shimmer": "shimmer 2.5s linear infinite",
        "morph-glow": "morphGlow 8s ease-in-out infinite",
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-8px)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        morphGlow: {
          "0%, 100%": { filter: "hue-rotate(0deg)" },
          "50%": { filter: "hue-rotate(45deg)" },
        },
      },
      boxShadow: {
        "glass": "0 8px 32px 0 rgba(0, 0, 0, 0.37)",
        "glow-sm": "0 0 15px -3px rgba(139, 92, 246, 0.3)",
        "glow-md": "0 0 25px -3px rgba(139, 92, 246, 0.45)",
        "glow-lg": "0 0 40px -5px rgba(139, 92, 246, 0.6)",
        "glow-cyan": "0 0 25px -3px rgba(6, 182, 212, 0.4)",
      },
    },
  },
  plugins: [],
};

export default config;

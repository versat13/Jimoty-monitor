/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: "#F7F4EE",      // 背景の温かみのあるオフホワイト
        ink: "#2B2A28",        // 本文の墨色
        indigo: {
          DEFAULT: "#3D4A6B",  // メインアクセント（深いインディゴ）
          soft: "#5C6B94",
        },
        clay: "#B5652B",       // 価格・数値の強調に使う焼き物のような橙
        alert: "#A6432E",      // NG判定・警告色
        line: "#E4DFD3",       // 罫線・区切り
      },
      fontFamily: {
        display: ["\"Zen Kaku Gothic New\"", "\"Hiragino Sans\"", "sans-serif"],
        body: ["\"Noto Sans JP\"", "\"Hiragino Sans\"", "sans-serif"],
        mono: ["\"JetBrains Mono\"", "monospace"],
      },
      borderRadius: {
        card: "18px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(43, 42, 40, 0.06), 0 4px 12px rgba(43, 42, 40, 0.05)",
      },
      keyframes: {
        "slide-up": {
          "0%": { transform: "translateY(24px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        // 2026-09-10追加: 取得範囲が「日数」モードのとき等、進捗の
        // 上限(何ページで終わるか)が不明な場合に使う不定形バー。
        // BottomNav直下の進捗表示 (components/BottomNav.jsx) 参照。
        "scan-progress-indeterminate": {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(300%)" },
        },
      },
      animation: {
        "slide-up": "slide-up 0.25s cubic-bezier(0.16, 1, 0.3, 1)",
        "scan-progress-indeterminate": "scan-progress-indeterminate 1.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
}

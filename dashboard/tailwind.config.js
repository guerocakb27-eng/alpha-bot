/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg:       "#080c14",
        panel:    "#0d1321",
        border:   "#1a2744",
        accent:   "#00d4ff",
        green:    "#00e676",
        red:      "#ff1744",
        yellow:   "#ffea00",
        muted:    "#4a6080",
        text:     "#c8d8f0",
        "text-dim": "#6a85a8",
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        panel: "0 0 0 1px rgba(26,39,68,0.6), 0 4px 32px rgba(0,212,255,0.04)",
      },
    },
  },
  plugins: [],
};

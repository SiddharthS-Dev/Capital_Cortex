/** @type {import('tailwindcss').Config} */
const token = (name) => `hsl(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // 8-px grid: spacing utilities stay on Tailwind's 4-px scale, but layouts use even steps (2, 4, 6…).
      colors: {
        background: token("background"),
        foreground: token("foreground"),
        card: { DEFAULT: token("card"), foreground: token("card-foreground") },
        muted: { DEFAULT: token("muted"), foreground: token("muted-foreground") },
        primary: { DEFAULT: token("primary"), foreground: token("primary-foreground") },
        accent: { DEFAULT: token("accent"), foreground: token("accent-foreground") },
        destructive: { DEFAULT: token("destructive"), foreground: token("destructive-foreground") },
        border: token("border"),
        input: token("input"),
        ring: token("ring"),
        band: {
          high: token("band-high"),
          watch: token("band-watch"),
          archive: token("band-archive"),
          insufficient: token("band-insufficient"),
        },
        demo: token("demo"),
        success: token("success"),
        warning: token("warning"),
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
      fontFamily: { sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"], mono: ["JetBrains Mono", "Consolas", "monospace"] },
    },
  },
  plugins: [],
};

import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "../../packages/ui/src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // "Ledger" design-system tokens (defined in globals.css). These flip
        // automatically with the OS dark preference via CSS variables.
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        "surface-sunken": "var(--surface-sunken)",

        ink: {
          DEFAULT: "var(--ink)",
          muted: "var(--ink-muted)",
          faint: "var(--ink-faint)",
        },

        line: {
          DEFAULT: "var(--line)",
          strong: "var(--line-strong)",
        },

        accent: {
          DEFAULT: "var(--accent)",
          hover: "var(--accent-hover)",
          soft: "var(--accent-soft)",
          ink: "var(--accent-ink)",
        },

        gold: {
          DEFAULT: "var(--gold)",
          soft: "var(--gold-soft)",
        },

        positive: { DEFAULT: "var(--positive)", soft: "var(--positive-soft)" },
        negative: { DEFAULT: "var(--negative)", soft: "var(--negative-soft)" },
        warning: { DEFAULT: "var(--warning)", soft: "var(--warning-soft)" },
        info: { DEFAULT: "var(--info)", soft: "var(--info-soft)" },

        // Back-compat: existing pages still reference `brand`. Map it to the
        // accent token so nothing breaks while pages migrate to token names.
        brand: {
          50: "var(--accent-soft)",
          500: "var(--accent)",
          600: "var(--accent-hover)",
          900: "var(--accent-ink)",
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "ui-serif", "Georgia", "serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
      },
    },
  },
  plugins: [],
};

export default config;

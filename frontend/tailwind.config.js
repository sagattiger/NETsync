/** @type {import('tailwindcss').Config} */
// All colors come from CSS variables (see src/index.css) so dark/light switch at runtime.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        gap: v("gap"),
        sidebar: v("sidebar"),
        surface: v("surface"),
        inset: v("inset"),
        chip: v("chip"),
        line: v("line"),
        edge: v("edge"),
        fg: v("fg"),
        fg2: v("fg2"),
        strong: v("strong"),
        muted: v("muted"),
        faint: v("faint"),
        active: v("active"),
        accent: v("accent"),
        primary: v("primary"),
        "on-primary": v("on-primary"),
        seg: v("seg"),
        "seg-edge": v("seg-edge"),
        "seg-active": v("seg-active"),
        "on-seg-active": v("on-seg-active"),
        ok: v("ok"),
        warn: v("warn"),
        crit: v("crit"),
        unknown: v("unknown"),
      },
      fontSize: { xxs: ["0.6875rem", "1rem"] },
      fontFamily: { sans: ["Inter", "Segoe UI", "Roboto", "system-ui", "sans-serif"] },
    },
  },
  plugins: [],
};

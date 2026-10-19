/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#1b1f24",
        panel: "#232930",
        panel2: "#2b323a",
        line: "#38414b",
        muted: "#8b98a5",
        accent: "#15d1a0",
        ok: "#13d389",
        warn: "#ffd703",
        crit: "#ff3232",
        unknown: "#ff8c1a",
      },
      fontSize: { xxs: "0.68rem" },
    },
  },
  plugins: [],
};

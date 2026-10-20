import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark";
export type ThemeChoice = Theme | "system";
const KEY = "netsync_theme";

const systemTheme = (): Theme => (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch { /* storage unavailable */ }
  return "system";
}

interface Ctx { theme: Theme; choice: ThemeChoice; setChoice: (c: ThemeChoice) => void; toggle: () => void }
const ThemeCtx = createContext<Ctx>({ theme: "dark", choice: "system", setChoice: () => {}, toggle: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readChoice);
  const [system, setSystem] = useState<Theme>(systemTheme);
  const theme = choice === "system" ? system : choice;

  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setSystem(systemTheme());
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);

  const setChoice = useCallback((c: ThemeChoice) => {
    setChoiceState(c);
    try { localStorage.setItem(KEY, c); } catch { /* storage unavailable */ }
  }, []);
  const toggle = useCallback(() => setChoice(theme === "dark" ? "light" : "dark"), [theme, setChoice]);

  return <ThemeCtx.Provider value={{ theme, choice, setChoice, toggle }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);

/** Read a theme token (e.g. "accent") as a CSS color string.
 *
 * Uses the legacy comma syntax on purpose: ECharts parses colors itself to derive hover
 * (emphasis) styles, and it does not understand "rgb(r g b / a)". With the space syntax a
 * hovered line got an empty stroke and a transparent fill, so the whole chart vanished. */
export function token(name: string, alpha = 1): string {
  const [r, g, b] = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim().split(/\s+/);
  return alpha === 1 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

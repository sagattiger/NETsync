import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useTheme } from "../theme";

/** Settings → General → Branding (public, so the sign-in page can use it too). */
export interface Branding { accent_color: string | null; logo: string | null; icon: string | null; app_name: string | null; time_format: string | null }
export function useBranding(): Branding | undefined {
  return useQuery({ queryKey: ["branding"], queryFn: () => api<Branding>("/plugins/general/branding"), staleTime: 300_000, retry: false }).data;
}
export const appName = (b?: Branding) => b?.app_name || "NETsync";

/** Applies the colour and the browser icon; call once near the root. */
export function useApplyBranding(): Branding | undefined {
  const b = useBranding();
  useEffect(() => {
    const root = document.documentElement;
    const hex = b?.accent_color;
    if (hex && /^#[0-9a-f]{6}$/i.test(hex)) {
      const n = parseInt(hex.slice(1), 16);
      root.style.setProperty("--accent", `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`);
    } else root.style.removeProperty("--accent");
    const link = document.querySelector<HTMLLinkElement>("link[rel~='icon']");
    if (link) link.href = b?.icon || "/favicon.svg";
  }, [b?.accent_color, b?.icon]);
  return b;
}

/** The app icon: the custom one from Settings → General, else NETsync's (pulse line into network nodes). */
export function LogoIcon({ className = "w-8 h-8" }: { className?: string }) {
  const b = useBranding();
  return <img src={b?.icon || "/favicon.svg"} alt="" aria-hidden="true" draggable={false} className={`${className} shrink-0 select-none object-contain`} />;
}

/** Logo and name for the sidebar and the sign-in page: a custom logo replaces both. */
export function BrandMark({ iconClass = "w-8 h-8", textClass = "text-lg" }: { iconClass?: string; textClass?: string }) {
  const b = useBranding();
  if (b?.logo) return <img src={b.logo} alt={appName(b)} draggable={false} className="h-8 max-w-[11rem] object-contain object-left select-none" />;
  return (
    <>
      <LogoIcon className={iconClass} />
      <span className={`${textClass} font-semibold text-strong tracking-tight`}>{appName(b)}</span>
    </>
  );
}

export type ArtName = "signin" | "empty-devices" | "empty-problems" | "empty-dashboards" | "empty-probes";

/** Line illustrations (public/brand/art), a dark and a light version each; follows the theme. */
export function Art({ name, className = "" }: { name: ArtName; className?: string }) {
  const { theme } = useTheme();
  return (
    <img
      src={`/brand/art/${name}-${theme === "dark" ? "dark" : "light"}.webp`}
      alt=""
      aria-hidden="true"
      draggable={false}
      loading="lazy"
      className={`select-none pointer-events-none ${className}`}
    />
  );
}

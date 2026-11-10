import { useTheme } from "../theme";

/** The NETsync app icon (pulse line turning into network nodes, white on the accent pink). */
export function LogoIcon({ className = "w-8 h-8" }: { className?: string }) {
  return <img src="/favicon.svg" alt="" aria-hidden="true" draggable={false} className={`${className} shrink-0 select-none`} />;
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

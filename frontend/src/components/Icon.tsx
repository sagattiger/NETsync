// Minimal stroke icon set (24x24 grid, currentColor).
const PATHS: Record<string, string> = {
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  alert: "M12 3 2 20h20L12 3zM12 10v4M12 17h.01",
  server: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l2 2H4l2-2zM10 20a2 2 0 0 0 4 0",
  users: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2 20c0-3.3 3.1-6 7-6s7 2.7 7 6M16 4.5a3.5 3.5 0 0 1 0 6.5M18 14c2.4.6 4 2.9 4 6",
  puzzle: "M9 4h6v3a2 2 0 1 0 4 0V4h1v6h-3a2 2 0 1 0 0 4h3v6h-6v-3a2 2 0 1 0-4 0v3H4v-6h3a2 2 0 1 0 0-4H4V4h5z",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
  menu: "M4 6h16M4 12h16M4 18h16",
  x: "M6 6l12 12M18 6 6 18",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
  router: "M3 14h18v6H3zM7 17h.01M11 17h.01M8 14l-2-5M16 14l2-5M9 7a4 4 0 0 1 6 0",
  switch: "M3 8h18v8H3zM6 12h.01M9 12h.01M12 12h.01M15 12h.01M18 12h.01",
  firewall: "M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3z",
  network: "M12 3v4M12 17v4M3 12h4M17 12h4M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z",
  refresh: "M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4",
  play: "M7 4l13 8-13 8V4z",
  plus: "M12 5v14M5 12h14",
  chevron: "M9 6l6 6-6 6",
  sidebar: "M4 5h16v14H4zM9 5v14",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12l2-1-1-3-2 .2-1.3-1.3L17 5l-3-1-1 2h-2L10 4 7 5l.3 2L6 8.3 4 8l-1 3 2 1v1l-2 1 1 3 2-.2L7.3 17 7 19l3 1 1-2h2l1 2 3-1-.3-2 1.3-1.3 2 .3 1-3-2-1v-1z",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01",
  command: "M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6z",
  arrow: "M5 12h14M13 6l6 6-6 6",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c2.5 2.4 3.8 5.4 3.8 9s-1.3 6.6-3.8 9c-2.5-2.4-3.8-5.4-3.8-9S9.5 5.4 12 3z",
  terminal: "M4 5h16v14H4zM7 9l3 3-3 3M12 15h5",
  pin: "M9 4h6l-1 5 3 3v2H7v-2l3-3-1-5zM12 14v6",
  sparkles: "M10 3l1.6 4.4L16 9l-4.4 1.6L10 15l-1.6-4.4L4 9l4.4-1.6L10 3zM18 13l.8 2.2L21 16l-2.2.8L18 19l-.8-2.2L15 16l2.2-.8L18 13z",
  message: "M4 5h16v11H9l-5 4V5z",
  edit: "M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  camera: "M4 8h3l2-3h6l2 3h3v11H4V8zM12 16a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  check: "M5 12l5 5L20 7",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-7 8-7s8 3 8 7",
  note: "M6 3h9l4 4v14H6V3zM14 3v5h5M9 13h7M9 17h5",
  lock: "M6 11h12v10H6V11zM8 11V7a4 4 0 0 1 8 0v4",
  palette: "M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.5 0-1.2-1-1.5-1-2.5 0-.8.7-1.5 1.5-1.5H17a4 4 0 0 0 4-4c0-4.7-4-8.5-9-8.5zM7.5 12h.01M10 7.5h.01M15 7.5h.01",
};

export function Icon({ name, className = "w-4 h-4", strokeWidth = 1.75 }: { name: keyof typeof PATHS | string; className?: string; strokeWidth?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d={PATHS[name] ?? PATHS.network} />
    </svg>
  );
}

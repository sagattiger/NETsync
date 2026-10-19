export function Avatar({ name, url, size = 28, className = "" }: { name: string | null | undefined; url?: string | null; size?: number; className?: string }) {
  const style = { width: size, height: size, fontSize: Math.max(10, size * 0.4) };
  if (url) {
    return <img src={url} alt={name ?? ""} style={style} className={`rounded-full object-cover shrink-0 bg-chip ${className}`} />;
  }
  const initials = (name ?? "?").split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("") || "?";
  return (
    <span style={style} className={`rounded-full bg-chip text-strong font-semibold uppercase inline-flex items-center justify-center shrink-0 ${className}`}>
      {initials}
    </span>
  );
}

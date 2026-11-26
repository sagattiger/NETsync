import { Warning } from "./types";

export function WarningBadges({ items }: { items: Warning[] }) {
  if (!items.length) return null;
  const byKind = new Map<string, Warning[]>();
  items.forEach((w) => byKind.set(w.kind, [...(byKind.get(w.kind) ?? []), w]));
  return (
    <span className="inline-flex flex-wrap gap-1">
      {[...byKind.values()].map((ws) => (
        <span key={ws[0].kind} title={ws.map((w) => w.text).join("\n")}
          className="text-xxs px-2 py-0.5 rounded-full border border-warn/40 text-warn bg-warn/10 whitespace-nowrap">
          ⚠ {ws.length > 1 ? `${ws.length} × ` : ""}{ws[0].text}
        </span>
      ))}
    </span>
  );
}

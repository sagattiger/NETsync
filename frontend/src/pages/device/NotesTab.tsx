import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, fmtDateTime } from "../../api";
import { Icon } from "../../components/Icon";
import { Markdown } from "../../components/Markdown";
import { Segmented } from "../../components/ui";

interface Note { content: string; updated_at: string | null; updated_by: string | null }

const TEMPLATE = `## Overview
Role of this device, where it sits in the network.

## Access
- Management: \`ssh admin@…\`
- Console / OOB:

## Contacts
- Owner:
- Vendor support / contract:

## Known issues
- [ ] …
`;

// [before, after, placeholder] wrapped around the selection.
const TOOLS: [string, string, string, string, string][] = [
  ["B", "**", "**", "bold", "Bold"],
  ["I", "_", "_", "italic", "Italic"],
  ["H", "## ", "", "Heading", "Heading"],
  ["•", "- ", "", "item", "List"],
  ["☐", "- [ ] ", "", "task", "Checklist"],
  ["</>", "`", "`", "code", "Inline code"],
  ["{ }", "```\n", "\n```", "code block", "Code block"],
  ["🔗", "[", "](https://)", "link text", "Link"],
];

export default function NotesTab({ deviceId, canEdit }: { deviceId: number; canEdit: boolean }) {
  const qc = useQueryClient();
  const { data: note, isLoading } = useQuery({ queryKey: ["note", deviceId], queryFn: () => api<Note>(`/devices/${deviceId}/note`) });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<"write" | "preview" | "split">("split");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const ta = useRef<HTMLTextAreaElement>(null);

  const dirty = editing && draft !== (note?.content ?? "");

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function start() {
    setDraft(note?.content || TEMPLATE);
    setEditing(true);
    setError("");
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      const saved = await api<Note>(`/devices/${deviceId}/note`, { method: "PUT", body: { content: draft } });
      qc.setQueryData(["note", deviceId], saved);
      setEditing(false);
    } catch (e: any) { setError(e.message); }
    setSaving(false);
  }

  function wrap(before: string, after: string, placeholder: string) {
    const el = ta.current;
    if (!el) return;
    const { selectionStart: s, selectionEnd: e } = el;
    const selected = draft.slice(s, e) || placeholder;
    const next = draft.slice(0, s) + before + selected + after + draft.slice(e);
    setDraft(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(s + before.length, s + before.length + selected.length);
    });
  }

  if (isLoading) return null;

  if (!editing) {
    return (
      <section className="card">
        <header className="card-title flex items-center justify-between gap-3">
          <span className="flex items-center gap-2"><Icon name="note" /> Notes</span>
          {canEdit && <button className="btn" onClick={start}><Icon name="edit" className="w-3.5 h-3.5" /> {note?.content ? "Edit" : "Write notes"}</button>}
        </header>
        <div className="p-5">
          {note?.content ? <Markdown source={note.content} /> : (
            <div className="text-center py-10">
              <div className="text-muted text-sm">No notes for this device yet.</div>
              <div className="text-muted text-xs mt-1">Document access, contacts, known issues, change history… Markdown is supported.</div>
            </div>
          )}
        </div>
        {note?.updated_at && (
          <footer className="px-5 py-3 border-t border-line text-xs text-muted" title={fmtDateTime(note.updated_at)}>
            Last edited by <span className="text-fg2">{note.updated_by}</span> · {fmtAgo(note.updated_at)}
          </footer>
        )}
      </section>
    );
  }

  return (
    <section className="card">
      <header className="px-4 py-2.5 border-b border-line flex flex-wrap items-center gap-2 justify-between">
        <div className="flex flex-wrap gap-0.5">
          {TOOLS.map(([label, before, after, ph, title]) => (
            <button key={title} title={title} onClick={() => wrap(before, after, ph)} disabled={mode === "preview"}
              className="min-w-[2rem] h-8 px-2 rounded-md text-xs font-semibold text-fg2 hover:bg-inset hover:text-strong disabled:opacity-30">
              {label}
            </button>
          ))}
        </div>
        <Segmented value={mode} onChange={setMode} options={[["write", "Write"], ["split", "Split"], ["preview", "Preview"]]} />
      </header>
      <div className={`grid ${mode === "split" ? "lg:grid-cols-2" : ""} min-h-[24rem]`}>
        {mode !== "preview" && (
          <textarea ref={ta} value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck
            onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); } }}
            className={`w-full min-h-[24rem] p-4 bg-transparent font-mono text-sm text-fg outline-none resize-y ${mode === "split" ? "lg:border-r border-line" : ""}`}
            placeholder="Write markdown…" autoFocus />
        )}
        {mode !== "write" && (
          <div className={`p-4 overflow-y-auto ${mode === "split" ? "hidden lg:block bg-inset/30" : ""}`}>
            {draft.trim() ? <Markdown source={draft} /> : <div className="text-muted text-sm">Nothing to preview</div>}
          </div>
        )}
      </div>
      <footer className="px-4 py-3 border-t border-line flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted">Markdown supported · <kbd className="font-mono">Ctrl+S</kbd> to save</span>
        <div className="flex items-center gap-2">
          {error && <span className="text-xs text-crit">{error}</span>}
          <button className="btn" onClick={() => { if (!dirty || confirm("Discard your changes?")) setEditing(false); }}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save notes"}</button>
        </div>
      </footer>
    </section>
  );
}

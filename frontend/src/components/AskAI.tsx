import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AIJob, api, AskTarget, fmtDateTime } from "../api";
import { Icon } from "./Icon";
import { Markdown } from "./Markdown";
import { Modal } from "./ui";

/** Whether the AI assistant is enabled and configured (hides the buttons otherwise). */
export function useAI() {
  return useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api<{ enabled: boolean; model: string | null }>("/plugins/ai/status"),
    staleTime: 60_000,
    retry: false,
  }).data;
}

/** Polls a job until it is done or failed. */
export function useAIJob(jobId: number | null) {
  return useQuery({
    queryKey: ["ai-job", jobId],
    queryFn: () => api<AIJob>(`/plugins/ai/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && ["done", "error"].includes(q.state.data.status) ? false : 2000),
  });
}

export function AIResult({ job, onRetry }: { job: AIJob | undefined; onRetry?: () => void }) {
  const started = useRef(Date.now());
  const [, tick] = useState(0);
  const busy = !job || job.status === "pending" || job.status === "running";
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [busy]);

  if (busy) {
    const secs = Math.round((Date.now() - started.current) / 1000);
    return (
      <div className="flex items-center gap-3 py-8 justify-center text-sm text-fg2">
        <span className="relative flex w-8 h-8 items-center justify-center rounded-full bg-accent/15 text-accent">
          <Icon name="sparkles" className="w-4 h-4 animate-pulse" />
        </span>
        <div>
          <div className="text-strong font-medium">{job?.status === "running" ? "Analysing…" : "Waiting in the queue…"}</div>
          <div className="text-xs text-muted">{secs}s · local models can take a minute</div>
        </div>
      </div>
    );
  }
  if (job.status === "error") {
    return (
      <div className="space-y-3">
        <div className="rounded-lg border border-crit/40 bg-crit/10 text-crit text-sm p-3">{job.error}</div>
        {onRetry && <button className="btn" onClick={onRetry}><Icon name="refresh" className="w-3.5 h-3.5" /> Try again</button>}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <Markdown source={job.result ?? ""} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xxs text-muted pt-2 border-t border-line">
        <span className="inline-flex items-center gap-1"><Icon name="sparkles" className="w-3 h-3 text-accent" /> {job.model}</span>
        <span>{job.auto ? "automatic" : `asked by ${job.requested_by}`}</span>
        <span>{fmtDateTime(job.finished_at)}</span>
        {job.duration != null && <span>{job.duration.toFixed(1)} s</span>}
        <span>AI can be wrong, verify before acting.</span>
      </div>
    </div>
  );
}

export function AIModal({ target, jobId: initialJob, title, onClose }: { target?: AskTarget; jobId?: number; title: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<number | null>(initialJob ?? null);
  const [error, setError] = useState("");
  const { data: job } = useAIJob(jobId);

  async function ask(force = false) {
    if (!target) return;
    setError("");
    try {
      const j = await api<AIJob>("/plugins/ai/ask", { body: { ...target, force } });
      setJobId(j.id);
      qc.setQueryData(["ai-job", j.id], j);
    } catch (e: any) { setError(e.message); }
  }

  useEffect(() => { if (!initialJob) ask(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  // refresh comments/syslog stickers once the answer lands
  useEffect(() => {
    if (job?.status === "done") {
      for (const key of ["history", "pinned", "syslog"]) qc.invalidateQueries({ queryKey: [key] });
    }
  }, [job?.status, qc]);

  return (
    <Modal title={title} onClose={onClose}>
      {error ? <div className="text-sm text-crit">{error}</div> : <AIResult job={job} onRetry={target ? () => ask(true) : undefined} />}
      <div className="mt-5 flex justify-end gap-2">
        {target && job?.status === "done" && (
          <button className="btn" onClick={() => ask(true)}><Icon name="refresh" className="w-3.5 h-3.5" /> Ask again</button>
        )}
        <button className="btn btn-primary" onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}

export function AskAIButton({ target, title, compact }: { target: AskTarget; title: string; compact?: boolean }) {
  const ai = useAI();
  const [open, setOpen] = useState(false);
  if (!ai?.enabled) return null;
  return (
    <>
      <button className={`btn btn-ghost ${compact ? "px-1.5 py-1" : "px-2 py-1"} text-accent hover:bg-accent/10`}
        onClick={(e) => { e.stopPropagation(); setOpen(true); }} title="Ask the AI assistant to explain this">
        <Icon name="sparkles" className="w-3.5 h-3.5" />{!compact && " Ask AI"}
      </button>
      {open && <AIModal target={target} title={title} onClose={() => setOpen(false)} />}
    </>
  );
}

import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, DeviceEvent, fmtDateTime } from "../../api";
import { CommentSticker, CommentThread, PinnedEvents } from "../../components/EventComments";
import { Icon } from "../../components/Icon";
import { Card, Empty, hideMd, Segmented, StateBadge } from "../../components/ui";

export default function EventsTab({ deviceId }: { deviceId: number }) {
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "problems" | "commented">("all");
  const { data = [], isLoading } = useQuery({
    queryKey: ["history", deviceId],
    queryFn: () => api<DeviceEvent[]>(`/devices/${deviceId}/history?limit=300`),
    refetchInterval: 60_000,
  });

  const rows = data.filter((e) =>
    filter === "all" ? true : filter === "problems" ? e.new_state > 0 : e.comments.length > 0);
  const key = (e: DeviceEvent) => `${e.service_id}-${e.time}`;

  return (
    <>
      <PinnedEvents deviceId={deviceId} />
      <Card
        title="State changes"
        actions={<Segmented value={filter} onChange={setFilter} options={[["all", "All"], ["problems", "Problems"], ["commented", "Commented"]]} />}
      >
        {isLoading ? <Empty>Loading…</Empty> : !rows.length ? <Empty>No events</Empty> : (
          <table className="tbl">
            <thead><tr>
              <th className="w-44">Time</th><th>Service</th><th>Change</th><th className={hideMd}>Output</th><th className="w-32 text-right">Comments</th>
            </tr></thead>
            <tbody>
              {rows.map((e) => {
                const k = key(e);
                const isOpen = open === k;
                return (
                  <Fragment key={k}>
                    <tr className={`group cursor-pointer ${e.pinned ? "bg-accent/[0.04]" : ""}`} onClick={() => setOpen(isOpen ? null : k)}>
                      <td className="text-xs whitespace-nowrap text-fg2">
                        <div className="flex items-center gap-2">
                          <Icon name="chevron" className={`w-3.5 h-3.5 text-muted transition-transform ${isOpen ? "rotate-90" : ""}`} />
                          {fmtDateTime(e.time)}
                        </div>
                      </td>
                      <td className="text-strong">{e.service}</td>
                      <td className="whitespace-nowrap">
                        <StateBadge state={e.old_state} small /><span className="text-muted mx-1.5 text-xs">→</span><StateBadge state={e.new_state} small />
                      </td>
                      <td className={`text-fg2 ${hideMd}`}>{e.output}</td>
                      <td className="text-right"><CommentSticker event={e} /></td>
                    </tr>
                    {isOpen && (
                      <tr><td colSpan={5} className="bg-inset/40 px-4 sm:pl-10"><CommentThread deviceId={deviceId} event={e} /></td></tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

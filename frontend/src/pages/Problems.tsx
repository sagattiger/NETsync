import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Service } from "../api";
import { Page, PageHeader } from "../components/Layout";
import ServiceTable from "../components/ServiceTable";
import { Card, Segmented } from "../components/ui";

export default function Problems() {
  const [showAcked, setShowAcked] = useState(true);
  const [minState, setMinState] = useState(1);
  const { data = [] } = useQuery({
    queryKey: ["problems", showAcked],
    queryFn: () => api<Service[]>(`/problems?include_acked=${showAcked}`),
    refetchInterval: 30_000,
  });
  // resolved rows (state OK) are kept and filtered by what they were
  const rows = data.filter((s) => (s.resolved ? s.problem_state ?? 0 : s.state) >= minState);

  return (
    <>
      <PageHeader
        title="Problems"
        sub={`${rows.filter((r) => !r.resolved).length} open · ${rows.filter((r) => r.resolved).length} recently resolved`}
        actions={
          <>
            <Segmented value={minState} onChange={setMinState} options={[[1, "Warning +"], [2, "Critical"]]} />
            <Segmented value={showAcked ? "all" : "open"} onChange={(v) => setShowAcked(v === "all")} options={[["all", "All"], ["open", "Unhandled"]]} />
          </>
        }
      />
      <Page>
        <Card><ServiceTable services={rows} showHost problems /></Card>
      </Page>
    </>
  );
}

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
  const rows = data.filter((s) => s.state >= minState);

  return (
    <>
      <PageHeader
        title="Problems"
        sub={`${rows.length} service problem${rows.length === 1 ? "" : "s"}`}
        actions={
          <>
            <Segmented value={minState} onChange={setMinState} options={[[1, "Warning +"], [2, "Critical"]]} />
            <Segmented value={showAcked ? "all" : "open"} onChange={(v) => setShowAcked(v === "all")} options={[["all", "All"], ["open", "Unhandled"]]} />
          </>
        }
      />
      <Page>
        <Card><ServiceTable services={rows} showHost /></Card>
      </Page>
    </>
  );
}

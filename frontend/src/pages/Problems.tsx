import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Service } from "../api";
import { PageHeader } from "../components/Layout";
import ServiceTable from "../components/ServiceTable";
import { Card } from "../components/ui";

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
        sub={`${rows.length} service problems`}
        actions={
          <>
            <select className="input text-xs" value={minState} onChange={(e) => setMinState(+e.target.value)}>
              <option value={1}>WARN and worse</option>
              <option value={2}>CRIT and worse</option>
            </select>
            <label className="btn cursor-pointer">
              <input type="checkbox" checked={showAcked} onChange={(e) => setShowAcked(e.target.checked)} /> show acknowledged
            </label>
          </>
        }
      />
      <div className="p-5">
        <Card><ServiceTable services={rows} showHost /></Card>
      </div>
    </>
  );
}

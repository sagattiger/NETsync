import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, Device, Service } from "../api";
import { PageHeader } from "../components/Layout";
import ServiceTable from "../components/ServiceTable";
import { Card, Empty, StateBadge, Tile } from "../components/ui";

export default function Overview() {
  const { data: ov } = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<{ devices: Record<string, number>; services: Record<string, number>; unhandled: number }>("/overview"),
  });
  const { data: problems = [] } = useQuery({
    queryKey: ["problems", "unhandled"],
    queryFn: () => api<Service[]>("/problems?include_acked=false"),
    refetchInterval: 30_000,
  });
  const { data: devices = [] } = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices") });
  const down = devices.filter((d) => d.status === 2);
  const s = ov?.services ?? {};

  return (
    <>
      <PageHeader title="Overview" sub="Unhandled problems across all devices you can see" />
      <div className="p-5 space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Tile label="Devices" value={devices.length} />
          <Tile label="Devices down" value={down.length} tone={down.length ? 2 : 0} />
          <Tile label="Services OK" value={s.OK ?? 0} tone={0} />
          <Tile label="Services WARN" value={s.WARN ?? 0} tone={(s.WARN ?? 0) ? 1 : undefined} />
          <Tile label="Services CRIT" value={s.CRIT ?? 0} tone={(s.CRIT ?? 0) ? 2 : undefined} />
        </div>

        {down.length > 0 && (
          <Card title="Devices down">
            <table className="tbl">
              <tbody>
                {down.map((d) => (
                  <tr key={d.id}>
                    <td className="w-16"><StateBadge state={d.status} small /></td>
                    <td><Link className="text-accent hover:underline" to={`/devices/${d.id}`}>{d.hostname}</Link></td>
                    <td className="text-gray-300">{d.status_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        <Card title={`Unhandled service problems (${problems.length})`}>
          {problems.length ? <ServiceTable services={problems} showHost /> : <Empty>All good, nothing to see here.</Empty>}
        </Card>
      </div>
    </>
  );
}

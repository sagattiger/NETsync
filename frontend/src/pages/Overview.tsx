import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, Device, Service } from "../api";
import { PinnedEvents } from "../components/EventComments";
import { Page, PageHeader } from "../components/Layout";
import ServiceTable from "../components/ServiceTable";
import { VendorLogo } from "../components/VendorLogo";
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
  const totalServices = Object.values(s).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHeader title="Overview" sub="Unhandled problems across the devices you can see" />
      <Page>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Tile label="Devices" value={devices.length} hint={down.length ? `${down.length} down` : "all reachable"} />
          <Tile label="Services" value={totalServices} hint={`${s.OK ?? 0} OK`} />
          <Tile label="Warning" value={s.WARN ?? 0} tone={(s.WARN ?? 0) ? 1 : undefined} />
          <Tile label="Critical" value={s.CRIT ?? 0} tone={(s.CRIT ?? 0) ? 2 : undefined} hint={`${ov?.unhandled ?? 0} unhandled`} />
        </div>

        {down.length > 0 && (
          <Card title="Devices down">
            <table className="tbl">
              <tbody>
                {down.map((d) => (
                  <tr key={d.id}>
                    <td className="w-12"><VendorLogo device={d} size={32} /></td>
                    <td><Link className="link" to={`/devices/${d.id}`}>{d.hostname}</Link><div className="text-xs text-muted">{d.status_reason}</div></td>
                    <td className="text-right"><StateBadge state={d.status} small /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        <PinnedEvents showDevice />

        <Card title={`Unhandled problems · ${problems.filter((p) => !p.resolved).length}`}>
          {problems.length ? <ServiceTable services={problems} showHost problems /> : <Empty>Everything is OK.</Empty>}
        </Card>
      </Page>
    </>
  );
}

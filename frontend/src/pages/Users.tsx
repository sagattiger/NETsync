import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Group } from "../api";
import { PageHeader } from "../components/Layout";
import { Card, Empty, Modal } from "../components/ui";

interface User { id: number; username: string; email: string | null; role: string; is_active: boolean; groups: Group[] }

export default function Users() {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [groupName, setGroupName] = useState("");
  const { data: users = [] } = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  const { data: groups = [] } = useQuery({ queryKey: ["groups"], queryFn: () => api<Group[]>("/groups") });

  async function addGroup() {
    if (!groupName) return;
    await api("/groups", { body: { name: groupName } });
    setGroupName("");
    qc.invalidateQueries({ queryKey: ["groups"] });
  }

  return (
    <>
      <PageHeader title="Users & groups" sub="Viewers and operators only see devices in their groups"
        actions={<button className="btn btn-primary" onClick={() => setAdding(true)}>+ New user</button>} />
      <div className="px-4 sm:px-6 pb-8 grid xl:grid-cols-3 gap-4">
        <Card title="Users" className="xl:col-span-2">
          <table className="tbl">
            <thead><tr><th>User</th><th>Email</th><th>Role</th><th>Groups</th><th></th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className={u.is_active ? "" : "opacity-50"}>
                  <td className="font-medium">{u.username}</td><td>{u.email ?? "-"}</td>
                  <td><span className="px-1.5 py-0.5 rounded bg-chip text-xxs uppercase">{u.role}</span></td>
                  <td className="text-xs">{u.role === "admin" ? "all" : u.groups.map((g) => g.name).join(", ") || "-"}</td>
                  <td className="text-right">
                    <button className="text-xs text-muted hover:text-crit"
                      onClick={async () => { await api(`/users/${u.id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["users"] }); }}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Device groups">
          {!groups.length && <Empty>No groups</Empty>}
          <table className="tbl"><tbody>
            {groups.map((g) => (
              <tr key={g.id}><td>{g.name}</td><td className="text-right">
                <button className="text-xs text-muted hover:text-crit"
                  onClick={async () => { await api(`/groups/${g.id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["groups"] }); }}>Delete</button>
              </td></tr>
            ))}
          </tbody></table>
          <div className="p-3 flex gap-2">
            <input className="input flex-1" placeholder="New group name" value={groupName} onChange={(e) => setGroupName(e.target.value)} />
            <button className="btn" onClick={addGroup}>Add</button>
          </div>
        </Card>
      </div>
      {adding && <AddUser groups={groups} onClose={() => { setAdding(false); qc.invalidateQueries({ queryKey: ["users"] }); }} />}
    </>
  );
}

function AddUser({ groups, onClose }: { groups: Group[]; onClose: () => void }) {
  const [f, setF] = useState({ username: "", password: "", email: "", role: "viewer", group_ids: [] as number[] });
  const [error, setError] = useState("");
  async function save() {
    try { await api("/users", { body: { ...f, email: f.email || null } }); onClose(); }
    catch (e: any) { setError(e.message); }
  }
  return (
    <Modal title="New user" onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <div><label className="label">Username</label><input className="input w-full" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></div>
        <div><label className="label">Password (min 8)</label><input className="input w-full" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
        <div><label className="label">Email</label><input className="input w-full" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
        <div><label className="label">Role</label>
          <select className="input w-full" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            <option value="viewer">Viewer</option><option value="operator">Operator</option><option value="admin">Admin</option>
          </select></div>
        <div className="col-span-2"><label className="label">Groups</label>
          <div className="flex flex-wrap gap-2">
            {groups.map((g) => (
              <label key={g.id} className="btn cursor-pointer">
                <input type="checkbox" checked={f.group_ids.includes(g.id)}
                  onChange={(e) => setF({ ...f, group_ids: e.target.checked ? [...f.group_ids, g.id] : f.group_ids.filter((x) => x !== g.id) })} />
                {g.name}
              </label>
            ))}
            {!groups.length && <span className="text-xs text-muted">Create groups first to scope non-admin users</span>}
          </div></div>
      </div>
      {error && <div className="text-crit text-xs mt-3">{error}</div>}
      <div className="mt-4 flex justify-end gap-2">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!f.username || f.password.length < 8}>Create</button>
      </div>
    </Modal>
  );
}

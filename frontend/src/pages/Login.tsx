import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, auth } from "../api";
import { Icon } from "../components/Icon";
import { useTheme } from "../theme";

export default function Login() {
  const nav = useNavigate();
  const { theme, toggle } = useTheme();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const { token } = await api<{ token: string }>("/auth/login", { body: { username, password } });
      auth.set(token);
      nav("/");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center px-4 py-10 bg-bg">
      <button onClick={toggle} className="fixed top-4 right-4 p-2 rounded-lg text-fg2 hover:bg-inset" aria-label="Toggle theme">
        <Icon name={theme === "dark" ? "sun" : "moon"} className="w-5 h-5" />
      </button>
      <form onSubmit={submit} className="card w-full max-w-sm p-7 space-y-5">
        <div className="flex items-center gap-3">
          <span className="w-10 h-10 rounded-xl bg-accent text-white font-bold flex items-center justify-center text-lg">N</span>
          <div>
            <div className="text-lg font-semibold text-strong tracking-tight">NETsync</div>
            <div className="text-xs text-muted">Network monitoring</div>
          </div>
        </div>
        <div>
          <label className="label">Username</label>
          <input className="input w-full" autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div>
          <label className="label">Password</label>
          <input className="input w-full" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <div className="text-crit text-xs">{error}</div>}
        <button className="btn btn-primary w-full py-2.5 text-sm" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}

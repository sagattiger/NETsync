import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, auth } from "../api";

export default function Login() {
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const { token } = await api<{ token: string }>("/auth/login", { body: { username, password } });
      auth.set(token);
      nav("/");
    } catch (err: any) {
      setError(err.message);
    }
  }

  return (
    <div className="h-full flex items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-9 h-9 rounded bg-accent text-black font-black flex items-center justify-center text-lg">N</div>
          <div className="text-xl font-semibold">NET<span className="text-accent">sync</span></div>
        </div>
        <div>
          <label className="label">Username</label>
          <input className="input w-full" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div>
          <label className="label">Password</label>
          <input className="input w-full" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <div className="text-crit text-xs">{error}</div>}
        <button className="btn btn-primary w-full justify-center py-2">Login</button>
      </form>
    </div>
  );
}

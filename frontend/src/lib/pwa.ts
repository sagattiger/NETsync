/** Installable app (PWA): registers the service worker and keeps Chrome's install prompt for an "Install app" button. */
import { useEffect, useState } from "react";

interface InstallPrompt extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferred: InstallPrompt | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((fn) => fn());

export function registerPwa() {
  if (!("serviceWorker" in navigator) || !window.isSecureContext || import.meta.env.DEV) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); // show our own button instead of the mini-infobar
    deferred = e as InstallPrompt;
    notify();
  });
  window.addEventListener("appinstalled", () => { deferred = null; notify(); });
}

/** The install prompt when Chrome offers one (null when installed already, not secure, or not supported). */
export function useInstallPrompt(): (() => Promise<void>) | null {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  }, []);
  if (!deferred) return null;
  return async () => {
    const p = deferred;
    if (!p) return;
    await p.prompt();
    await p.userChoice.catch(() => null);
    deferred = null;
    notify();
  };
}

/** Why Chrome can't offer installing here (for the About page), or null. */
export function installBlocker(): string | null {
  if (window.matchMedia?.("(display-mode: standalone)").matches) return null;
  if (!window.isSecureContext) {
    return "Installing the app needs HTTPS: open NETsync through an https:// address (for example behind your reverse proxy).";
  }
  return null;
}

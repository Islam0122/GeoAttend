import { useEffect, useState } from "react";

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferred: BeforeInstallPromptEvent | null = null;
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as BeforeInstallPromptEvent;
  });
}

export function useInstallPrompt() {
  const [canPrompt, setCan] = useState(!!deferred);
  const installed = typeof window !== "undefined" && window.matchMedia?.("(display-mode: standalone)").matches;
  useEffect(() => {
    const h = () => setCan(true);
    window.addEventListener("beforeinstallprompt", h);
    return () => window.removeEventListener("beforeinstallprompt", h);
  }, []);
  return {
    canPrompt,
    installed,
    prompt: async () => {
      if (!deferred) return;
      await deferred.prompt();
      deferred = null;
      setCan(false);
    },
  };
}

export function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || import.meta.env.DEV) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => console.warn("Service worker registration failed", err));
  });
}

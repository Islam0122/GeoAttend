import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { queryClient } from "@/api/queryClient";
import { App } from "@/App";
import { OfflineSync } from "@/components/layout/OfflineSync";
import { registerServiceWorker } from "@/features/pwa";
import { bootstrapSession } from "@/features/session";
import { applyTheme, useUiStore } from "@/stores/ui";
import "./index.css";

applyTheme(useUiStore.getState().theme);
matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyTheme(useUiStore.getState().theme));
registerServiceWorker();
void bootstrapSession();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        <OfflineSync />
        <Toaster richColors position="top-center" />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);

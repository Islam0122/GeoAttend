import { create } from "zustand";

type Theme = "light" | "dark" | "system";
const KEY = "geoattend.theme";

function read(): Theme {
  try {
    return (localStorage.getItem(KEY) as Theme) || "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && typeof matchMedia !== "undefined" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

interface UiState {
  theme: Theme;
  sidebarOpen: boolean;
  online: boolean;
  setTheme(t: Theme): void;
  setSidebarOpen(v: boolean): void;
  setOnline(v: boolean): void;
}

export const useUiStore = create<UiState>((set) => ({
  theme: read(),
  sidebarOpen: false,
  online: typeof navigator === "undefined" ? true : navigator.onLine,
  setTheme: (theme) => {
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* ignore */
    }
    applyTheme(theme);
    set({ theme });
  },
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setOnline: (online) => set({ online }),
}));

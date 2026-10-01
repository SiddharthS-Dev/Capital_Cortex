import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark" | "system";

interface UIState {
  theme: Theme;
  setTheme: (t: Theme) => void;
  copilotOpen: boolean;
  setCopilotOpen: (open: boolean) => void;
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  navCollapsed: boolean;
  toggleNav: () => void;
}

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      theme: "system",
      setTheme: (theme) => set({ theme }),
      copilotOpen: false,
      setCopilotOpen: (copilotOpen) => set({ copilotOpen }),
      paletteOpen: false,
      setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
      navCollapsed: false,
      toggleNav: () => set((s) => ({ navCollapsed: !s.navCollapsed })),
    }),
    { name: "cortex-ui", partialize: (s) => ({ theme: s.theme, navCollapsed: s.navCollapsed }) },
  ),
);

export function applyTheme(theme: Theme) {
  const dark =
    theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

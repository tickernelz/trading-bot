export const SCREENS = [
  { id: "ringkas", label: "Ringkas", group: "Pantau", tab: true },
  { id: "grafik", label: "Grafik", group: "Pantau", tab: true },
  { id: "aksi", label: "Aksi", group: "Pantau", tab: true },
  { id: "swarm", label: "Swarm", group: "Pantau", tab: false },
  { id: "kontrol", label: "Kontrol", group: "Kendali", tab: true },
  { id: "konfigurasi", label: "Konfigurasi", group: "Kendali", tab: false },
  { id: "provider", label: "Provider dan key", group: "Kendali", tab: false },
  { id: "riwayat", label: "Riwayat", group: "Catatan", tab: false },
  { id: "ab", label: "A vs B", group: "Catatan", tab: false },
  { id: "audit", label: "Audit", group: "Catatan", tab: false },
  { id: "sistem", label: "Sistem", group: "Sistem", tab: false },
  { id: "lainnya", label: "Lainnya", group: null, tab: true },
] as const;

export type Screen = (typeof SCREENS)[number]["id"];

export const GROUPS = ["Pantau", "Kendali", "Catatan", "Sistem"] as const;

export function inGroup(group: string) {
  return SCREENS.filter((s) => s.group === group);
}

export function tabFor(screen: Screen): Screen {
  return SCREENS.find((s) => s.id === screen)?.tab ? screen : "lainnya";
}

function parse(hash: string): Screen {
  const id = hash.replace(/^#/, "");
  return SCREENS.find((s) => s.id === id)?.id ?? "ringkas";
}

class Route {
  screen = $state<Screen>(parse(location.hash));

  constructor() {
    addEventListener("hashchange", () => {
      this.screen = parse(location.hash);
      scrollTo({ top: 0 });
    });
  }
}

export const route = new Route();

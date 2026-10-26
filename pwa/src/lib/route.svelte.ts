import { t } from "./i18n";

export const SCREENS = [
  { id: "ringkas", label: t("nav.ringkas"), group: "pantau", tab: true },
  { id: "grafik", label: t("nav.grafik"), group: "pantau", tab: true },
  { id: "aksi", label: t("nav.aksi"), group: "pantau", tab: true },
  { id: "swarm", label: t("nav.swarm"), group: "pantau", tab: false },
  { id: "kontrol", label: t("nav.kontrol"), group: "kendali", tab: true },
  { id: "konfigurasi", label: t("nav.konfigurasi"), group: "kendali", tab: false },
  { id: "provider", label: t("nav.provider"), group: "kendali", tab: false },
  { id: "riwayat", label: t("nav.riwayat"), group: "catatan", tab: false },
  { id: "ab", label: t("nav.ab"), group: "catatan", tab: false },
  { id: "audit", label: t("nav.audit"), group: "catatan", tab: false },
  { id: "sistem", label: t("nav.sistem"), group: "sistem", tab: false },
  { id: "lainnya", label: t("nav.lainnya"), group: null, tab: true },
] as const;

export type Screen = (typeof SCREENS)[number]["id"];

export const GROUPS = [
  { id: "pantau", label: t("nav.group.pantau") },
  { id: "kendali", label: t("nav.group.kendali") },
  { id: "catatan", label: t("nav.group.catatan") },
  { id: "sistem", label: t("nav.group.sistem") },
] as const;

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

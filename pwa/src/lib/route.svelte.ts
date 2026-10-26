import { t } from "./i18n";

export const SCREENS = [
  { id: "ringkas", label: t("nav.ringkas") },
  { id: "grafik", label: t("nav.grafik") },
  { id: "aksi", label: t("nav.aksi") },
  { id: "swarm", label: t("nav.swarm") },
  { id: "sistem", label: t("nav.sistem") },
] as const;

export type Screen = (typeof SCREENS)[number]["id"];

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

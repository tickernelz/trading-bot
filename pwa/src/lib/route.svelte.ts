import { t } from "./i18n";

export const SCREENS = [
  { id: "summary", label: t("nav.summary"), group: "watch", tab: true },
  { id: "chart", label: t("nav.chart"), group: "watch", tab: true },
  { id: "activity", label: t("nav.activity"), group: "watch", tab: true },
  { id: "swarm", label: t("nav.swarm"), group: "watch", tab: false },
  { id: "control", label: t("nav.control"), group: "control", tab: true },
  { id: "config", label: t("nav.config"), group: "control", tab: false },
  { id: "provider", label: t("nav.provider"), group: "control", tab: false },
  { id: "history", label: t("nav.history"), group: "records", tab: false },
  { id: "ab", label: t("nav.ab"), group: "records", tab: false },
  { id: "audit", label: t("nav.audit"), group: "records", tab: false },
  { id: "system", label: t("nav.system"), group: "system", tab: false },
  { id: "more", label: t("nav.more"), group: null, tab: true },
] as const;

export type Screen = (typeof SCREENS)[number]["id"];

export const GROUPS = [
  { id: "watch", label: t("nav.group.watch") },
  { id: "control", label: t("nav.group.control") },
  { id: "records", label: t("nav.group.records") },
  { id: "system", label: t("nav.group.system") },
] as const;

export function inGroup(group: string) {
  return SCREENS.filter((s) => s.group === group);
}

export function tabFor(screen: Screen): Screen {
  return SCREENS.find((s) => s.id === screen)?.tab ? screen : "more";
}

function parse(hash: string): Screen {
  const id = hash.replace(/^#/, "");
  return SCREENS.find((s) => s.id === id)?.id ?? "summary";
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

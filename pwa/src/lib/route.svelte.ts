export const SCREENS = [
  { id: "ringkas", label: "Ringkas" },
  { id: "grafik", label: "Grafik" },
  { id: "aksi", label: "Aksi" },
  { id: "swarm", label: "Swarm" },
  { id: "sistem", label: "Sistem" },
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

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

type Listener = (event: { waitUntil: (p: Promise<unknown>) => void; data?: unknown; notification?: unknown }) => void;

function worker(windows: { visibilityState: string }[], shownAfter: number) {
  const listeners: Record<string, Listener> = {};
  const badge: (number | "clear")[] = [];
  const self = {
    location: { origin: "https://bot.example" },
    addEventListener: (name: string, fn: Listener) => (listeners[name] = fn),
    navigator: {
      setAppBadge: async (n: number) => void badge.push(n),
      clearAppBadge: async () => void badge.push("clear"),
    },
    clients: { matchAll: async () => windows, openWindow: async () => null },
    registration: {
      showNotification: async () => undefined,
      getNotifications: async () => Array.from({ length: shownAfter }),
    },
  };
  const source = readFileSync(new URL("../sw/sw.js", import.meta.url), "utf8").replace("__SW_VERSION__", "t").replace("__SW_ASSETS__", "[]");
  new Function("self", "caches", "fetch", source)(self, {}, fetch);
  async function fire(name: string, data?: unknown) {
    const pending: Promise<unknown>[] = [];
    listeners[name]({ waitUntil: (p) => void pending.push(p), data, notification: { close() {}, data: {} } });
    await Promise.all(pending);
  }
  return { fire, badge };
}

const push = { json: () => ({ kind: "fill", title: "t", body: "b" }) };

describe("app badge", () => {
  it("counts shown notifications while no window is visible", async () => {
    const w = worker([{ visibilityState: "hidden" }], 2);
    await w.fire("push", push);
    expect(w.badge).toEqual([2]);
  });

  it("clears while a window is visible", async () => {
    const w = worker([{ visibilityState: "visible" }], 2);
    await w.fire("push", push);
    expect(w.badge).toEqual(["clear"]);
  });

  it("clears once the last notification is dismissed", async () => {
    const w = worker([], 0);
    await w.fire("notificationclose");
    expect(w.badge).toEqual(["clear"]);
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import type { Api } from "../src/lib/api";
import { inLang, memoryStorage } from "./lang";

const subscription = { endpoint: "https://push.invalid/1", toJSON: () => ({ endpoint: "https://push.invalid/1" }) };

function fakeApi() {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  const api = { post: async (path: string, body: Record<string, unknown>) => void posts.push({ path, body }) } as unknown as Api;
  return { api, posts };
}

async function pushIn(code: string, storage: Storage) {
  const push = await inLang(code, () => import("../src/lib/push"));
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("navigator", { serviceWorker: { getRegistration: async () => ({ pushManager: { getSubscription: async () => subscription } }) } });
  return push;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("push subscription language", () => {
  it("sends the active language once per change and again after a switch", async () => {
    const storage = memoryStorage();
    const { api, posts } = fakeApi();
    await (await pushIn("id", storage)).syncPushLang(api);
    await (await pushIn("id", storage)).syncPushLang(api);
    expect(posts).toEqual([{ path: "/gw/v1/push/subscriptions", body: expect.objectContaining({ lang: "id", subscription: { endpoint: subscription.endpoint } }) }]);
    await (await pushIn("en", storage)).syncPushLang(api);
    expect(posts.map((p) => p.body.lang)).toEqual(["id", "en"]);
  });

  it("posts nothing when the browser holds no subscription", async () => {
    const { api, posts } = fakeApi();
    const push = await inLang("id", () => import("../src/lib/push"));
    vi.stubGlobal("localStorage", memoryStorage());
    vi.stubGlobal("navigator", { serviceWorker: { getRegistration: async () => undefined } });
    await push.syncPushLang(api);
    expect(posts).toEqual([]);
  });
});

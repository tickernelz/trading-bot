import { describe, expect, it } from "vitest";
import { Backoff } from "../src/lib/backoff";
import { FeedClient, UNAUTHORIZED_CLOSE, type Clock, type LinkInfo, type SocketLike } from "../src/lib/feed";

class FakeClock implements Clock {
  t = 0;
  private seq = 0;
  private timers = new Map<number, { at: number; fn: () => void; every?: number }>();
  now() {
    return this.t;
  }
  setTimeout(fn: () => void, ms: number) {
    const id = ++this.seq;
    this.timers.set(id, { at: this.t + ms, fn });
    return id;
  }
  clearTimeout(h: unknown) {
    this.timers.delete(h as number);
  }
  setInterval(fn: () => void, ms: number) {
    const id = ++this.seq;
    this.timers.set(id, { at: this.t + ms, fn, every: ms });
    return id;
  }
  clearInterval(h: unknown) {
    this.timers.delete(h as number);
  }
  advance(ms: number) {
    const end = this.t + ms;
    for (;;) {
      const due = [...this.timers.entries()].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      const [id, timer] = due;
      this.t = timer.at;
      if (timer.every) timer.at += timer.every;
      else this.timers.delete(id);
      timer.fn();
    }
    this.t = end;
  }
}

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: string[] = [];
  closedWith: number | null = null;
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;
  constructor(readonly url: string) {}
  send(data: string) {
    this.sent.push(data);
  }
  close(code?: number) {
    this.closedWith = code ?? 1000;
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  message(obj: object) {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }
  drop(code = 1006) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

function setup(options: { online?: () => boolean } = {}) {
  const clock = new FakeClock();
  const sockets: FakeSocket[] = [];
  const links: LinkInfo[] = [];
  const events: string[] = [];
  let lastSeq: number | null = null;
  const client = new FeedClient({
    url: () => "ws://gw/events",
    socket: (url) => {
      const s = new FakeSocket(url);
      sockets.push(s);
      return s;
    },
    clock,
    backoff: new Backoff({ baseMs: 1000, maxMs: 8000, factor: 2, stableMs: 10000 }, () => 1),
    isOnline: options.online,
    onEvent: (e) => {
      lastSeq = e.seq;
      events.push(e.type);
    },
    onLink: (info) => links.push(info),
    greeting: () => (lastSeq === null ? [{ type: "subscribe" }] : [{ type: "resume", last_seq: lastSeq }, { type: "subscribe" }]),
  });
  return { clock, sockets, links, events, client };
}

describe("Backoff", () => {
  it("doubles the ceiling up to the cap and keeps jitter in the upper half", () => {
    const top = new Backoff({ baseMs: 1000, maxMs: 8000, factor: 2, stableMs: 10000 }, () => 1);
    expect([top.next(), top.next(), top.next(), top.next(), top.next()]).toEqual([1000, 2000, 4000, 8000, 8000]);
    const bottom = new Backoff({ baseMs: 1000, maxMs: 8000, factor: 2, stableMs: 10000 }, () => 0);
    expect([bottom.next(), bottom.next()]).toEqual([500, 1000]);
  });

  it("resets only after a stable connection", () => {
    const b = new Backoff({ baseMs: 1000, maxMs: 8000, factor: 2, stableMs: 10000 }, () => 1);
    b.next();
    b.next();
    b.connectedFor(9999);
    expect(b.next()).toBe(4000);
    b.connectedFor(10000);
    expect(b.next()).toBe(1000);
  });
});

describe("FeedClient", () => {
  it("reconnects with growing delays and resumes from the last sequence", () => {
    const { clock, sockets, links, events, client } = setup();
    client.start();
    sockets[0].open();
    sockets[0].message({ type: "entry", seq: 41, ts: "", data: {} });
    sockets[0].drop();
    expect(links.at(-1)).toMatchObject({ state: "waiting", retryAt: 1000 });
    clock.advance(999);
    expect(sockets).toHaveLength(1);
    clock.advance(1);
    expect(sockets).toHaveLength(2);
    sockets[1].drop();
    expect(links.at(-1)).toMatchObject({ state: "waiting", retryAt: clock.now() + 2000, attempts: 2 });
    clock.advance(2000);
    sockets[2].open();
    expect(sockets[2].sent.map((s) => JSON.parse(s))).toEqual([{ type: "resume", last_seq: 41 }, { type: "subscribe" }]);
    expect(events).toEqual(["entry"]);
  });

  it("keeps the first disconnect time across failed retries", () => {
    const { clock, sockets, links, client } = setup();
    client.start();
    sockets[0].open();
    clock.advance(5000);
    sockets[0].drop();
    clock.advance(1000);
    sockets[1].drop();
    expect(links.at(-1)?.closedAt).toBe(5000);
  });

  it("closes a silent socket when no pong arrives", () => {
    const { clock, sockets, links, client } = setup();
    client.start();
    sockets[0].open();
    clock.advance(20000);
    expect(JSON.parse(sockets[0].sent.at(-1)!)).toEqual({ type: "ping" });
    clock.advance(9999);
    expect(links.at(-1)?.state).toBe("open");
    clock.advance(1);
    expect(sockets[0].closedWith).toBe(4000);
    expect(links.at(-1)?.state).toBe("waiting");
  });

  it("answers server pings and treats a pong as liveness", () => {
    const { clock, sockets, links, client } = setup();
    client.start();
    sockets[0].open();
    sockets[0].message({ type: "ping" });
    expect(JSON.parse(sockets[0].sent.at(-1)!)).toEqual({ type: "pong" });
    clock.advance(20000);
    sockets[0].message({ type: "pong", ts: "" });
    clock.advance(15000);
    expect(links.at(-1)?.state).toBe("open");
  });

  it("stops retrying when the gateway rejects the token", () => {
    const { clock, sockets, links, client } = setup();
    client.start();
    sockets[0].open();
    sockets[0].drop(UNAUTHORIZED_CLOSE);
    clock.advance(60000);
    expect(links.at(-1)?.state).toBe("unauthorized");
    expect(sockets).toHaveLength(1);
  });

  it("waits for the network instead of burning retries while offline", () => {
    let online = true;
    const { clock, sockets, links, client } = setup({ online: () => online });
    client.start();
    sockets[0].open();
    online = false;
    sockets[0].drop();
    clock.advance(60000);
    expect(links.at(-1)?.state).toBe("offline");
    expect(sockets).toHaveLength(1);
    online = true;
    client.retryNow();
    expect(sockets).toHaveLength(2);
  });
});

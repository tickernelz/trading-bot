import { Backoff } from "./backoff";
import type { FeedEvent } from "./types";

export type LinkState = "idle" | "connecting" | "open" | "waiting" | "offline" | "unauthorized";

export interface SocketLike {
  readyState: number;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number; reason?: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export interface Clock {
  now(): number;
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
  setInterval(fn: () => void, ms: number): unknown;
  clearInterval(handle: unknown): void;
}

export const realClock: Clock = {
  now: () => Date.now(),
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (h) => globalThis.clearTimeout(h as ReturnType<typeof setTimeout>),
  setInterval: (fn, ms) => globalThis.setInterval(fn, ms),
  clearInterval: (h) => globalThis.clearInterval(h as ReturnType<typeof setInterval>),
};

export interface LinkInfo {
  state: LinkState;
  retryAt: number | null;
  attempts: number;
  openedAt: number | null;
  closedAt: number | null;
}

export interface FeedOptions {
  url: () => string;
  onEvent: (event: FeedEvent) => void;
  onLink: (info: LinkInfo) => void;
  greeting: () => object[];
  socket?: (url: string) => SocketLike;
  clock?: Clock;
  backoff?: Backoff;
  isOnline?: () => boolean;
  pingEveryMs?: number;
  pongWithinMs?: number;
}

export const UNAUTHORIZED_CLOSE = 4401;
const OPEN = 1;

export class FeedClient {
  private ws: SocketLike | null = null;
  private retryTimer: unknown = null;
  private pingTimer: unknown = null;
  private pongTimer: unknown = null;
  private stopped = true;
  private info: LinkInfo = { state: "idle", retryAt: null, attempts: 0, openedAt: null, closedAt: null };
  private readonly clock: Clock;
  private readonly backoff: Backoff;
  private readonly socket: (url: string) => SocketLike;
  private readonly isOnline: () => boolean;

  constructor(private readonly options: FeedOptions) {
    this.clock = options.clock ?? realClock;
    this.backoff = options.backoff ?? new Backoff();
    this.socket = options.socket ?? ((url) => new WebSocket(url) as unknown as SocketLike);
    this.isOnline = options.isOnline ?? (() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  }

  get link(): LinkInfo {
    return this.info;
  }

  start(): void {
    this.stopped = false;
    this.backoff.reset();
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearRetry();
    this.teardown(1000);
    this.publish({ state: "idle", retryAt: null });
  }

  retryNow(): void {
    if (this.stopped) return;
    if (this.info.state === "waiting" || this.info.state === "offline") {
      this.clearRetry();
      this.connect();
    }
  }

  wentOffline(): void {
    if (this.stopped || this.info.state === "unauthorized") return;
    this.clearRetry();
    this.teardown(4000);
    this.publish({ state: "offline", retryAt: null, closedAt: this.info.closedAt ?? this.clock.now() });
  }

  send(message: object): void {
    if (this.ws && this.ws.readyState === OPEN) this.ws.send(JSON.stringify(message));
  }

  private publish(patch: Partial<LinkInfo>): void {
    this.info = { ...this.info, ...patch, attempts: this.backoff.attempts };
    this.options.onLink(this.info);
  }

  private connect(): void {
    if (!this.isOnline()) {
      this.publish({ state: "offline", retryAt: null });
      return;
    }
    this.publish({ state: "connecting", retryAt: null });
    const ws = this.socket(this.options.url());
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.publish({ state: "open", openedAt: this.clock.now(), closedAt: null });
      for (const message of this.options.greeting()) this.send(message);
      this.pingTimer = this.clock.setInterval(() => this.ping(), this.options.pingEveryMs ?? 20000);
    };
    ws.onmessage = (ev) => {
      if (this.ws !== ws) return;
      this.receive(ev.data);
    };
    ws.onerror = () => undefined;
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.closed(ev.code);
    };
  }

  private receive(raw: unknown): void {
    if (typeof raw !== "string") return;
    let message: FeedEvent;
    try {
      message = JSON.parse(raw) as FeedEvent;
    } catch {
      return;
    }
    if (this.pongTimer !== null) {
      this.clock.clearTimeout(this.pongTimer);
      this.pongTimer = null;
    }
    if (message.type === "pong") return;
    if (message.type === "ping") {
      this.send({ type: "pong" });
      return;
    }
    this.options.onEvent(message);
  }

  private ping(): void {
    this.send({ type: "ping" });
    if (this.pongTimer !== null) return;
    this.pongTimer = this.clock.setTimeout(() => {
      this.pongTimer = null;
      const ws = this.ws;
      this.closed(4000);
      ws?.close(4000, "pong timeout");
    }, this.options.pongWithinMs ?? 10000);
  }

  private closed(code: number): void {
    const openedAt = this.info.state === "open" ? this.info.openedAt : null;
    this.teardown(null);
    if (openedAt !== null) this.backoff.connectedFor(this.clock.now() - openedAt);
    const closedAt = this.info.closedAt ?? this.clock.now();
    if (this.stopped) return;
    if (code === UNAUTHORIZED_CLOSE) {
      this.publish({ state: "unauthorized", retryAt: null, closedAt });
      return;
    }
    if (!this.isOnline()) {
      this.publish({ state: "offline", retryAt: null, closedAt });
      return;
    }
    const delay = this.backoff.next();
    this.publish({ state: "waiting", retryAt: this.clock.now() + delay, closedAt });
    this.retryTimer = this.clock.setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  private teardown(code: number | null): void {
    if (this.pingTimer !== null) this.clock.clearInterval(this.pingTimer);
    if (this.pongTimer !== null) this.clock.clearTimeout(this.pongTimer);
    this.pingTimer = null;
    this.pongTimer = null;
    const ws = this.ws;
    this.ws = null;
    if (ws && code !== null) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      ws.close(code);
    }
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) this.clock.clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }
}

import type { Api } from "./api";

export type PushSupport = "supported" | "ios-needs-home-screen" | "unsupported";

export function isIos(): boolean {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

export function isStandalone(): boolean {
  return matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

export function pushSupport(): PushSupport {
  const capable = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (isIos() && !isStandalone()) return "ios-needs-home-screen";
  return capable ? "supported" : "unsupported";
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export const PUSH_KINDS = [
  { kind: "fill", label: "Order terisi (beli atau jual)" },
  { kind: "risk_breach", label: "Batas rugi harian atau total terlewati" },
  { kind: "kill_switch", label: "Kill switch aktif atau bot berhenti" },
  { kind: "heartbeat_lost", label: "Heartbeat bot hilang" },
  { kind: "quorum_failed", label: "Kuorum swarm gagal" },
  { kind: "daily_summary", label: "Ringkasan harian" },
] as const;

export async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

export async function enablePush(api: Api): Promise<PushSubscription> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error(permission === "denied" ? "denied" : "dismissed");
  const reg = await navigator.serviceWorker.ready;
  const { public_key } = await api.get<{ public_key: string }>("/gw/v1/push/key");
  const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) }));
  await api.post("/gw/v1/push/subscriptions", { subscription: sub.toJSON(), kinds: PUSH_KINDS.map((k) => k.kind) });
  return sub;
}

export async function disablePush(api: Api): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) return;
  await api.del("/gw/v1/push/subscriptions", { endpoint: sub.endpoint });
  await sub.unsubscribe();
}

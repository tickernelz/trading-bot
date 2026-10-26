import { t, type Key } from "./i18n";
import type { Decision, FearGreedClass, VoterRecord } from "./types";

const CHOICES: Record<string, Key> = { izinkan: "choice.izinkan", kecilkan: "choice.kecilkan", lewati: "choice.lewati" };
const REASONS: Record<string, Key> = { quorum_not_met: "reason.quorum_not_met", spread_too_wide: "reason.spread_too_wide" };
const FEAR_GREED: Record<FearGreedClass, Key> = {
  "Extreme Fear": "fng.extreme_fear",
  Fear: "fng.fear",
  Neutral: "fng.neutral",
  Greed: "fng.greed",
  "Extreme Greed": "fng.extreme_greed",
};

export function choiceText(choice: string | null | undefined): string {
  if (!choice) return "-";
  const key = CHOICES[choice];
  return key ? t(key) : choice;
}

export function reasonText(reason: string | null | undefined): string {
  if (!reason) return "-";
  const key = REASONS[reason];
  return key ? t(key) : reason;
}

export function verdictText(d: Decision): string {
  if (d.status === "skip") return t("verdict.skipped", { reason: reasonText(d.reason) });
  return choiceText(d.verdict);
}

export function answerText(v: VoterRecord): string {
  if (v.status === "timeout") return t("voter.timeout");
  if (v.status === "invalid") return t("voter.invalid");
  if (v.status !== "ok") return t("voter.failed");
  return choiceText(v.answers?.action?.choice);
}

export function fearGreedText(value: FearGreedClass): string {
  return t(FEAR_GREED[value]);
}

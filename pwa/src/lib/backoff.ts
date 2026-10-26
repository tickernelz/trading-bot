export interface BackoffPolicy {
  baseMs: number;
  maxMs: number;
  factor: number;
  stableMs: number;
}

export const DEFAULT_BACKOFF: BackoffPolicy = { baseMs: 1000, maxMs: 30000, factor: 2, stableMs: 10000 };

export class Backoff {
  private attempt = 0;

  constructor(
    private readonly policy: BackoffPolicy = DEFAULT_BACKOFF,
    private readonly random: () => number = Math.random,
  ) {}

  get attempts(): number {
    return this.attempt;
  }

  next(): number {
    const ceiling = Math.min(this.policy.maxMs, this.policy.baseMs * this.policy.factor ** this.attempt);
    this.attempt += 1;
    const floor = ceiling / 2;
    return Math.round(floor + this.random() * (ceiling - floor));
  }

  connectedFor(ms: number): void {
    if (ms >= this.policy.stableMs) this.attempt = 0;
  }

  reset(): void {
    this.attempt = 0;
  }
}

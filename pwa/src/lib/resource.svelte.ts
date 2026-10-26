import { faultOf, type Fault } from "./state";

export class Resource<T> {
  data = $state<T | null>(null);
  loading = $state(false);
  fault = $state<Fault | null>(null);
  loadedAt = $state<number | null>(null);
  private run = 0;

  constructor(private readonly fetcher: () => Promise<T>) {}

  async load(): Promise<void> {
    const run = ++this.run;
    this.loading = true;
    try {
      const data = await this.fetcher();
      if (run !== this.run) return;
      this.data = data;
      this.fault = null;
      this.loadedAt = Date.now();
    } catch (error) {
      if (run !== this.run) return;
      this.fault = faultOf(error, Date.now());
    } finally {
      if (run === this.run) this.loading = false;
    }
  }
}

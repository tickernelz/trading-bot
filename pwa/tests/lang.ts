import { vi } from "vitest";

export function memoryStorage(initial: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(initial));
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
}

export async function inLang<T>(stored: string | null, load: () => Promise<T>): Promise<T> {
  vi.resetModules();
  vi.stubGlobal("localStorage", memoryStorage(stored === null ? {} : { "tb.lang": stored }));
  try {
    return await load();
  } finally {
    vi.unstubAllGlobals();
  }
}

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { PROVIDER_TYPES } from "../src/lib/providerTypes";

describe("provider types", () => {
  it("match the schema the gateway validates against", () => {
    const source = readFileSync(fileURLToPath(new URL("../../engine/settings.py", import.meta.url)), "utf8");
    const block = /ProviderType = Literal\[([^\]]*)\]/.exec(source);
    expect(block).not.toBeNull();
    const schema = [...(block as RegExpExecArray)[1].matchAll(/"([a-z-]+)"/g)].map((match) => match[1]);
    expect([...PROVIDER_TYPES].sort()).toEqual([...schema].sort());
  });
});

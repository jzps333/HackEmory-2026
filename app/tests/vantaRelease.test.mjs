// Run: cd app && node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { releaseVanta } from "../src/components/desktop/vantaRelease.ts";

test("releaseVanta frees the WebGL context before Vanta removes its canvas", () => {
  const calls = [];
  const instance = {
    renderer: { dispose: () => calls.push("dispose"), forceContextLoss: () => calls.push("forceContextLoss") },
    destroy: () => calls.push("destroy"),
  };
  releaseVanta(instance);
  assert.deepEqual(calls, ["dispose", "forceContextLoss", "destroy"]);
});

test("releaseVanta still destroys when there is no renderer", () => {
  let destroyed = false;
  releaseVanta({ destroy: () => { destroyed = true; } });
  assert.equal(destroyed, true);
});

test("releaseVanta never throws (failed init, or nothing to release)", () => {
  assert.doesNotThrow(() => releaseVanta({ renderer: { dispose() { throw new Error("gone"); } }, destroy() { throw new Error("not a child"); } }));
  assert.doesNotThrow(() => releaseVanta(null));
});

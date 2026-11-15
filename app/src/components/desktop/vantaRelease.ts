// No imports, so `node --test tests/` can run it directly.

interface VantaLike {
  renderer?: { dispose?: () => void; forceContextLoss?: () => void } | null;
  destroy?: () => void;
}

/**
 * Tear down a Vanta effect and give its WebGL context back to the browser. Vanta 0.5.24's destroy() only removes
 * the canvas; without dispose() + forceContextLoss() each re-entry would hold another context until Chrome's
 * limit (~16) starts killing others (e.g. the Radar background). Never throws.
 */
export function releaseVanta(instance: VantaLike | null | undefined): void {
  if (!instance) return;
  try {
    instance.renderer?.dispose?.();
    instance.renderer?.forceContextLoss?.();
  } catch {
    // Already lost or never created.
  }
  try {
    instance.destroy?.();
  } catch {
    // An effect whose init failed has no canvas to remove.
  }
}

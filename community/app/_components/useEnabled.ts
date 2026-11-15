"use client";

import { useCallback, useRef, useState } from "react";
import { ApiError, errorText, setPluginEnabled } from "@/lib/api";

/** The demo agent's enabled-plugin set, with optimistic toggles that roll back on error. */
export function useEnabled() {
  const [enabled, setEnabled] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const enabledRef = useRef<Set<string>>(new Set());
  const pendingRef = useRef<Set<string>>(new Set());

  const commit = useCallback((next: Set<string>) => {
    enabledRef.current = next;
    setEnabled(next);
  }, []);

  const reset = useCallback(
    (ids: string[]) => {
      commit(new Set(ids));
      setErrors({});
    },
    [commit],
  );

  const toggle = useCallback(
    async (id: string) => {
      if (pendingRef.current.has(id)) return;
      const was = enabledRef.current.has(id);
      const optimistic = new Set(enabledRef.current);
      if (was) optimistic.delete(id);
      else optimistic.add(id);
      commit(optimistic);
      pendingRef.current.add(id);
      setPending(new Set(pendingRef.current));
      setErrors((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      try {
        const next = new Set(await setPluginEnabled(id, !was));
        // Take the server's answer, but keep the optimistic value of other toggles still in flight.
        for (const other of pendingRef.current) {
          if (other === id) continue;
          if (enabledRef.current.has(other)) next.add(other);
          else next.delete(other);
        }
        commit(next);
      } catch (e) {
        const next = new Set(enabledRef.current);
        if (was) next.add(id);
        else next.delete(id);
        commit(next);
        // 403 needs_verification: the API's own message says why; otherwise prefix what failed.
        const msg =
          e instanceof ApiError && e.code === "needs_verification"
            ? e.message
            : `Couldn't ${was ? "disable" : "enable"} it. ${errorText(e)}`;
        setErrors((prev) => ({ ...prev, [id]: msg }));
      } finally {
        pendingRef.current.delete(id);
        setPending(new Set(pendingRef.current));
      }
    },
    [commit],
  );

  return { enabled, pending, errors, reset, toggle };
}

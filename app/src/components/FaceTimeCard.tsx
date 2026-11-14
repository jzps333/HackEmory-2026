"use client";

import { useState } from "react";
import { callMe } from "@/lib/api";

type State = { kind: "idle" } | { kind: "busy" } | { kind: "ringing" } | { kind: "error"; msg: string };

function friendly(err: unknown): string {
  const m = err instanceof Error ? err.message : "";
  if (m.includes("403")) return "This phone isn't set up for ScanSafe calls yet. Text “hi” to +1 (650) 444-4331, then try again.";
  if (m.includes("429")) return "We just called you. Please wait half a minute and try again.";
  if (m.includes("503") || m.includes("502")) return "Our calling service is busy right now. The result above is still correct.";
  return "We couldn't start the call right now. The result above is still correct.";
}

/** "Watch it live on FaceTime": ScanSafe calls the user and opens the scanned link on our computer, live. */
export default function FaceTimeCard({ url, phone, location }: { url: string; phone: string; location: [number, number] | null }) {
  const [state, setState] = useState<State>({ kind: "idle" });

  async function start() {
    setState({ kind: "busy" });
    try {
      await callMe(url, phone, location);
      setState({ kind: "ringing" });
    } catch (e) {
      setState({ kind: "error", msg: friendly(e) });
    }
  }

  return (
    <section className="card facetime-card" aria-labelledby="ft-h">
      <h2 id="ft-h">Want to see it?</h2>
      <p>We can FaceTime you and open this page on our computer while you watch. Nothing opens on your phone.</p>
      {state.kind === "ringing" ? (
        <p className="notice" role="status">Your phone will ring in a few seconds. Answer the FaceTime from ScanSafe.</p>
      ) : (
        <button type="button" className="btn btn-primary" onClick={start} disabled={state.kind === "busy"}>
          {state.kind === "busy" ? "Calling you…" : "FaceTime me and show me"}
        </button>
      )}
      {state.kind === "error" && <p className="notice bad" role="alert">{state.msg}</p>}
    </section>
  );
}

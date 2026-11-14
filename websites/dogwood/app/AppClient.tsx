"use client";

/**
 * The (made-up) official Dogwood Parking app, opened from ScanSafe with /dogwood/app?s=<session>.
 *
 * Network: only the ScanSafe API's Dogwood operator endpoints.
 *   GET  {API}/operators/dogwood/app-state?s=<session>   every 1.5 s
 *        -> {meter_id, operator, plate, hours, rate_per_hour_sol, amount_sol,
 *            status: "choose" | "waiting_for_approval" | "paid", receipt?: {signature, explorer_url, paid_at}}
 *   POST {API}/operators/dogwood/app-state?s=<session>   {hours}   when the hours control changes
 * "Pay with linked ScanSafe account" never pays: it only shows "Waiting for your approval in
 * ScanSafe…". The payment happens when the person taps Pay in the ScanSafe app, and this page
 * shows the receipt once the server says "paid".
 * Stable selectors for the ScanSafe operator automation: data-testid="plate", "hours-1".."hours-4",
 * "pay", "waiting", "receipt".
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, AppBar, AppIcon, GREEN, Shell, amountFor, errorText, hoursText, queryParam, solText } from "../shared";

type Receipt = { signature?: string; explorer_url?: string; paid_at?: string | number };
type Status = "choose" | "waiting_for_approval" | "paid";
type AppState = {
  meter_id: string; operator: string; plate: string; hours: number | null;
  rate_per_hour_sol: number; amount_sol: number | null; status: Status; receipt: Receipt | null;
};

const POLL_MS = 1500;
const LOCAL_HOLD_MS = 4000;        // after a tap here, the server's hours win again after this long
const HOURS = [1, 2, 3, 4];
const TOKEN_RE = /^[A-Za-z0-9._~-]{8,512}$/;
const DEFAULT_OPERATOR = "Dogwood Lot & Meter Co.";

function validHours(h: unknown): h is number {
  return typeof h === "number" && Number.isInteger(h) && HOURS.includes(h);
}

function str(x: unknown, n: number): string {
  return typeof x === "string" || typeof x === "number" ? String(x).slice(0, n) : "";
}

function parseState(x: unknown): AppState | null {
  if (!x || typeof x !== "object") return null;
  const o = x as Record<string, unknown>;
  const status = o.status === "paid" || o.status === "waiting_for_approval" ? o.status : "choose";
  const rate = typeof o.rate_per_hour_sol === "number" && o.rate_per_hour_sol > 0 ? o.rate_per_hour_sol : 0.01;
  const r = o.receipt && typeof o.receipt === "object" ? (o.receipt as Record<string, unknown>) : null;
  return {
    meter_id: str(o.meter_id, 20) || "42",
    operator: str(o.operator, 60) || DEFAULT_OPERATOR,
    plate: str(o.plate, 10).toUpperCase(),
    hours: validHours(o.hours) ? o.hours : null,
    rate_per_hour_sol: rate,
    amount_sol: typeof o.amount_sol === "number" && Number.isFinite(o.amount_sol) ? o.amount_sol : null,
    status,
    receipt: r ? {
      signature: str(r.signature, 120),
      explorer_url: str(r.explorer_url, 400),
      paid_at: typeof r.paid_at === "number" ? r.paid_at : str(r.paid_at, 60),
    } : null,
  };
}

function timeText(t: string | number | undefined): string {
  if (t === undefined || t === "") return "Just now";
  let ms = typeof t === "number" ? (t > 1e12 ? t : t * 1000) : Date.parse(t);
  if (!Number.isFinite(ms) && typeof t === "string" && /^\d+(\.\d+)?$/.test(t)) ms = Number(t) * 1000;
  if (!Number.isFinite(ms)) return String(t).slice(0, 40);
  return new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function shortSig(sig: string): string {
  return sig.length > 20 ? `${sig.slice(0, 8)}…${sig.slice(-8)}` : sig;
}

function LinkedChip() {
  return (
    <span style={{ fontSize: 13, fontWeight: 700, border: "1.5px solid #ffffffb0", borderRadius: 999, padding: "3px 10px" }}>
      ScanSafe linked
    </span>
  );
}

export default function AppClient() {
  const [token, setToken] = useState("");
  const [phase, setPhase] = useState<"loading" | "nosession" | "ready">("loading");
  const [why, setWhy] = useState<"missing" | "expired">("missing");
  const [st, setSt] = useState<AppState | null>(null);
  const [plate, setPlate] = useState("");
  const [hours, setHours] = useState(1);
  const [payRequested, setPayRequested] = useState(false);
  const [choosingAgain, setChoosingAgain] = useState(false);
  const [offline, setOffline] = useState(false);
  const [postErr, setPostErr] = useState("");
  const plateTouched = useRef(false);
  const localAt = useRef(0);
  const firstLoad = useRef(true);

  useEffect(() => {
    const s = queryParam("s");
    if (!TOKEN_RE.test(s)) {
      setWhy("missing");
      setPhase("nosession");
      return;
    }
    setToken(s);
  }, []);

  const stateUrl = token ? `${API_BASE}/operators/dogwood/app-state?s=${encodeURIComponent(token)}` : "";

  useEffect(() => {
    if (!stateUrl) return;
    let stopped = false;
    let inflight = false;
    const tick = async () => {
      if (stopped || inflight) return;
      inflight = true;
      const ctl = new AbortController();
      const timeout = setTimeout(() => ctl.abort(), 5000);
      try {
        const res = await fetch(stateUrl, { cache: "no-store", signal: ctl.signal });
        if ([401, 403, 404, 410].includes(res.status)) {
          stopped = true;
          setWhy("expired");
          setPhase("nosession");
          return;
        }
        if (!res.ok) throw new Error(`status ${res.status}`);
        const s = parseState(await res.json());
        if (!s) throw new Error("bad response");
        if (stopped) return;
        setOffline(false);
        setSt(s);
        if (s.hours !== null && (firstLoad.current || Date.now() - localAt.current > LOCAL_HOLD_MS)) setHours(s.hours);
        if (!plateTouched.current && s.plate) setPlate(s.plate);
        firstLoad.current = false;
        setPhase("ready");
        if (s.status === "paid") stopped = true;      // the receipt doesn't change any more
      } catch {
        if (!stopped) setOffline(true);
      } finally {
        clearTimeout(timeout);
        inflight = false;
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { stopped = true; clearInterval(id); };
  }, [stateUrl]);

  const postHours = useCallback(async (n: number) => {
    if (!stateUrl) return;
    setPostErr("");
    try {
      const res = await fetch(stateUrl, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hours: n }), cache: "no-store",
      });
      if (!res.ok) setPostErr(`Couldn't change the hours. ${await errorText(res)}`);
    } catch {
      setPostErr("Couldn't reach Dogwood to change the hours. Check your connection and try again.");
    }
  }, [stateUrl]);

  function pick(n: number) {
    localAt.current = Date.now();
    if (n === hours) return;
    setHours(n);
    postHours(n);
  }

  function pay() {
    localAt.current = Date.now();
    if (st && st.hours !== hours) postHours(hours);   // make sure the server has these hours
    setChoosingAgain(false);
    setPayRequested(true);                            // nothing is paid here: ScanSafe asks the person
  }

  function changeHours() {
    setPayRequested(false);
    setChoosingAgain(true);
  }

  if (phase === "nosession") {
    return (
      <Shell header={<AppBar />}>
        <div className="dw-card" style={{ textAlign: "center", padding: "28px 18px" }} data-testid="no-session">
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 14 }}><AppIcon size={72} /></div>
          <h1>Open this from ScanSafe</h1>
          {why === "missing" ? (
            <p>Dogwood Parking opens from the ScanSafe app when you pay for parking. Go back to ScanSafe and
              choose to pay for parking there.</p>
          ) : (
            <p>This parking session has ended, or the link is no longer valid. Go back to ScanSafe and start
              again.</p>
          )}
          <p className="dw-muted" style={{ marginBottom: 0 }}>You don&apos;t need to type anything here.</p>
        </div>
      </Shell>
    );
  }

  if (phase === "loading" || !st) {
    return (
      <Shell header={<AppBar />}>
        <div className="dw-card" style={{ textAlign: "center", padding: "28px 18px" }} aria-live="polite">
          <div className="dw-spin" aria-hidden="true" />
          <h2>Opening Dogwood Parking…</h2>
          {offline && <p className="dw-muted" style={{ marginBottom: 0 }}>Can&apos;t reach Dogwood right now. Trying again…</p>}
        </div>
      </Shell>
    );
  }

  const rate = st.rate_per_hour_sol;
  const total = st.hours === hours && st.amount_sol !== null ? st.amount_sol : amountFor(rate, hours);
  const meterLabel = `Meter ${st.meter_id} · ${st.operator}`;
  const shownPlate = plate.trim() || st.plate;

  if (st.status === "paid") {
    const r = st.receipt || {};
    const paidHours = st.hours ?? hours;
    const paidAmount = st.amount_sol ?? amountFor(rate, paidHours);
    const explorer = r.explorer_url && /^https:\/\//i.test(r.explorer_url) ? r.explorer_url : "";
    return (
      <Shell header={<AppBar right={<LinkedChip />} />}>
        <div className="dw-card" data-testid="receipt" style={{ textAlign: "center", paddingTop: 24 }}>
          <svg width="76" height="76" viewBox="0 0 76 76" aria-hidden="true" style={{ display: "block", margin: "0 auto 10px" }}>
            <circle cx="38" cy="38" r="38" fill={GREEN} />
            <path d="M22 39 L33 50 L55 27" fill="none" stroke="#fff" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <h1>You&apos;re parked</h1>
          <p className="dw-muted">{meterLabel}</p>
          <div style={{ textAlign: "left", marginTop: 8 }}>
            <div className="dw-row"><span>License plate</span><span>{shownPlate || "—"}</span></div>
            <div className="dw-row"><span>Time</span><span>{hoursText(paidHours)}</span></div>
            <div className="dw-row"><span>Paid</span><span>{solText(paidAmount)} SOL (devnet)</span></div>
            <div className="dw-row"><span>When</span><span>{timeText(r.paid_at)}</span></div>
            {r.signature && <div className="dw-row"><span>Transaction</span><span>{shortSig(r.signature)}</span></div>}
          </div>
          {explorer && (
            <a className="dw-btn secondary" style={{ marginTop: 14 }} href={explorer} target="_blank" rel="noopener noreferrer"
              data-testid="explorer">
              View on Solana Explorer
            </a>
          )}
        </div>
        <p className="dw-muted" style={{ textAlign: "center" }}>Paid with your linked ScanSafe account.</p>
      </Shell>
    );
  }

  const waiting = payRequested || (st.status === "waiting_for_approval" && !choosingAgain);

  return (
    <Shell header={<AppBar right={<LinkedChip />} />}>
      {offline && <div className="dw-note" role="status">Reconnecting to Dogwood…</div>}
      {postErr && <div className="dw-alert" role="alert">{postErr}</div>}

      <div className="dw-card" data-testid="meter">
        <div className="dw-muted" style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", fontSize: 12 }}>
          Parking meter
        </div>
        <h1 style={{ fontSize: 21, margin: "2px 0 4px" }}>{meterLabel}</h1>
        <div className="dw-muted">Rate {solText(rate)} SOL per hour · devnet test SOL</div>
      </div>

      {waiting ? (
        <div className="dw-card" data-testid="waiting" style={{ textAlign: "center" }} aria-live="polite">
          <div className="dw-spin" aria-hidden="true" />
          <h2 style={{ fontSize: 20 }}>Waiting for your approval in ScanSafe…</h2>
          <p>Open ScanSafe and tap <strong>Pay</strong> to approve {solText(total)} SOL for {hoursText(hours)}.</p>
          <div style={{ textAlign: "left" }}>
            <div className="dw-row"><span>License plate</span><span>{shownPlate || "—"}</span></div>
            <div className="dw-row"><span>Time</span><span>{hoursText(hours)}</span></div>
            <div className="dw-row"><span>Total</span><span>{solText(total)} SOL</span></div>
          </div>
          <p className="dw-muted" style={{ margin: "12px 0" }}>Nothing is paid until you approve it in ScanSafe.</p>
          <button type="button" className="dw-btn secondary" data-testid="change" onClick={changeHours}>Change hours</button>
        </div>
      ) : (
        <>
          <div className="dw-card">
            <label className="dw-label" htmlFor="dw-plate">License plate</label>
            <input id="dw-plate" className="dw-input" data-testid="plate" value={plate} autoComplete="off" autoCapitalize="characters"
              spellCheck={false} maxLength={10} placeholder="ABC1234"
              onChange={(e) => {
                plateTouched.current = true;
                setPlate(e.target.value.toUpperCase().replace(/[^A-Z0-9 -]/g, "").slice(0, 10));
              }} />
          </div>

          <div className="dw-card">
            <div className="dw-label" id="dw-hours-label">How long?</div>
            <div className="dw-seg" role="group" aria-labelledby="dw-hours-label">
              {HOURS.map((n) => (
                <button key={n} type="button" data-testid={`hours-${n}`} aria-pressed={n === hours} onClick={() => pick(n)}
                  aria-label={hoursText(n)}>
                  {n} h
                </button>
              ))}
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="dw-row"><span>Rate</span><span>{solText(rate)} SOL / hour</span></div>
              <div className="dw-row" style={{ fontSize: 20 }}><span>Total · {hoursText(hours)}</span><span data-testid="total">{solText(total)} SOL</span></div>
            </div>
          </div>

          <button type="button" className="dw-btn" data-testid="pay" onClick={pay} disabled={!plate.trim()}>
            Pay with linked ScanSafe account
          </button>
          <p className="dw-muted" style={{ textAlign: "center", marginTop: 10 }}>
            {plate.trim() ? "You'll approve the payment in ScanSafe." : "Enter your license plate to continue."}
          </p>
        </>
      )}
    </Shell>
  );
}

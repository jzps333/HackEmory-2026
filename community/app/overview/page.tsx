import { ArrowUpRight, PhoneIncoming, PhoneOutgoing, MessageSquare, Puzzle } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import PageHeader from "../_components/PageHeader";

export const metadata: Metadata = { title: "Overview" };

// Demo values only: a 555 number and made-up activity.
const ACTIVITY = [
  { icon: PhoneOutgoing, text: "Outgoing call ended", who: "contact ending in 61", ago: "3 h" },
  { icon: PhoneIncoming, text: "Incoming call ended", who: "contact ending in 07", ago: "5 h" },
  { icon: MessageSquare, text: "Message sent", who: "contact ending in 61", ago: "6 h" },
  { icon: PhoneIncoming, text: "Missed call", who: "contact ending in 42", ago: "1 d" },
];

export default function OverviewPage() {
  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Your lines, live calls and recent activity for ScanSafe demo."
        checked="11:22 PM"
      />

      <section className="stats" aria-label="Project stats">
        <div className="stat">
          <div className="stat-label">FaceTime today</div>
          <div className="stat-value mono">42 trial min left</div>
        </div>
        <div className="stat">
          <div className="stat-label">Messages</div>
          <div className="stat-value">Not linked</div>
        </div>
        <div className="stat">
          <div className="stat-label">Live calls</div>
          <div className="stat-value mono">0</div>
        </div>
        <div className="stat">
          <div className="stat-label">Plan</div>
          <div className="stat-value">Free trial</div>
        </div>
      </section>

      <div className="two-col">
        <section className="card">
          <div className="card-head">
            <h2 className="card-title">Lines</h2>
            <Link href="/lines" className="link">
              Integration settings
            </Link>
          </div>
          <div className="line-row">
            <div>
              <div className="line-number mono">+1 555 0100</div>
              <div className="muted small">FaceTime · iMessage · Demo line</div>
            </div>
            <span className="pill pill-green">Active</span>
          </div>
          <div className="card-foot muted small">
            Agent: ScanSafe FaceTime agent. Plugins come from{" "}
            <Link href="/plugins" className="link">
              Community plugins
            </Link>
            .
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h2 className="card-title">Live activity</h2>
            <Link href="/calls" className="link">
              All calls
            </Link>
          </div>
          <ul className="activity">
            {ACTIVITY.map(({ icon: Icon, text, who, ago }, i) => (
              <li key={i} className="activity-row">
                <span className="activity-icon" aria-hidden="true">
                  <Icon size={14} strokeWidth={1.75} />
                </span>
                <span className="activity-text">
                  {text} <span className="muted">· {who}</span>
                </span>
                <span className="activity-ago mono">{ago}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <Link href="/plugins" className="card promo">
        <span className="promo-icon" aria-hidden="true">
          <Puzzle size={18} strokeWidth={1.75} />
        </span>
        <span className="promo-text">
          <span className="promo-title">New: Community plugins</span>
          <span className="muted small">Open-source skills for your Chert agent, like the ScanSafe QR checker.</span>
        </span>
        <ArrowUpRight size={16} className="muted-icon" />
      </Link>
    </>
  );
}

"use client";

import { AlertTriangle, Box, Check, Lock, Plus, RefreshCw, Server, ShieldAlert, ShieldCheck } from "lucide-react";
import { NEEDS_VERIFICATION_HELP, type Plugin } from "@/lib/api";

export function VerifiedBadge({ verified }: { verified: boolean }) {
  return verified ? (
    <span className="badge badge-verified">
      <ShieldCheck size={13} strokeWidth={2} />
      Verified
    </span>
  ) : (
    <span className="badge badge-unverified">
      <ShieldAlert size={13} strokeWidth={2} />
      Unverified
    </span>
  );
}

export function RunsOn({ plugin }: { plugin: Plugin }) {
  return plugin.runs_on === "vm" ? (
    <span className="meta-item">
      <Box size={13} strokeWidth={1.75} />
      Runs in locked-down VM
    </span>
  ) : (
    <span className="meta-item">
      <Server size={13} strokeWidth={1.75} />
      Runs on server
    </span>
  );
}

export function Installs({ n }: { n: number }) {
  return (
    <span className="meta-item">
      <span className="mono">{n.toLocaleString("en-US")}</span> {n === 1 ? "install" : "installs"}
    </span>
  );
}

type EnableProps = {
  enabled: boolean;
  verified: boolean;
  pending: boolean;
  onToggle: () => void;
  name: string;
};

/** Unverified plugins can't be turned on (the API answers 403 needs_verification); turning one off always works. */
export function EnableButton({ enabled, verified, pending, onToggle, name }: EnableProps) {
  if (!verified && !enabled) {
    return (
      <button
        type="button"
        className="btn btn-blocked"
        disabled
        title={NEEDS_VERIFICATION_HELP}
        aria-label={`${name} needs verification. ${NEEDS_VERIFICATION_HELP}`}
      >
        <Lock size={14} strokeWidth={2} />
        Needs verification
      </button>
    );
  }
  return (
    <button
      type="button"
      className={`btn ${enabled ? "btn-enabled" : "btn-secondary"}`}
      aria-pressed={enabled}
      aria-label={`${enabled ? "Disable" : "Enable"} ${name} for my agent`}
      onClick={onToggle}
      disabled={pending}
    >
      {enabled ? <Check size={15} strokeWidth={2} /> : <Plus size={15} strokeWidth={2} />}
      {enabled ? "Enabled" : "Enable"}
    </button>
  );
}

export function VerifyHelp({ verified, enabled }: { verified: boolean; enabled: boolean }) {
  return !verified && !enabled ? <p className="verify-help small">{NEEDS_VERIFICATION_HELP}</p> : null;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="error-box" role="alert">
      <AlertTriangle size={16} strokeWidth={1.75} />
      <span className="error-text">{message}</span>
      <button type="button" className="btn btn-secondary btn-small" onClick={onRetry}>
        <RefreshCw size={13} />
        Retry
      </button>
    </div>
  );
}

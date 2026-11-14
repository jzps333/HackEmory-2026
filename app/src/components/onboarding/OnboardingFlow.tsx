"use client";

import { useState, type FormEvent } from "react";
import { Icon } from "@/components/onboarding/Icon";
import "./onboarding.css";
import {
  LocationAccessError,
  requestCurrentLocation,
} from "@/lib/geolocation";
import type {
  OnboardingCompletionHandler,
  OnboardingData,
} from "@/lib/onboarding";

const emptyData: OnboardingData = {
  fullName: "",
  email: "",
  phone: "",
  location: null,
  walletAddress: null,
  facetimeOk: false,
};

export function OnboardingFlow({
  onComplete,
}: {
  onComplete?: OnboardingCompletionHandler;
}) {
  const [step, setStep] = useState(1);
  const [data, setData] = useState<OnboardingData>(emptyData);
  const [locationLoading, setLocationLoading] = useState(false);
  const [locationError, setLocationError] = useState("");
  const [walletMessage, setWalletMessage] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [completionError, setCompletionError] = useState("");
  const [finishing, setFinishing] = useState(false);

  function updateProfile(field: "fullName" | "email" | "phone", value: string) {
    setData((current) => ({ ...current, [field]: value }));
  }

  function continueFromProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) return;

    setData((current) => ({
      ...current,
      fullName: current.fullName.trim(),
      email: current.email.trim(),
      phone: current.phone.trim(),
    }));
    setStep(2);
  }

  async function useMyLocation() {
    setLocationLoading(true);
    setLocationError("");

    try {
      const precise = await requestCurrentLocation();
      // Round to ~100 m before we keep it: enough to pin a scam on the map, not your front door.
      const location = {
        latitude: Math.round(precise.latitude * 1000) / 1000,
        longitude: Math.round(precise.longitude * 1000) / 1000,
      };
      setData((current) => ({ ...current, location }));
    } catch (error) {
      setLocationError(
        error instanceof LocationAccessError
          ? error.message
          : "We couldn't access your location. Please try again.",
      );
    } finally {
      setLocationLoading(false);
    }
  }

  async function finishOnboarding() {
    if (finishing || completed) return;

    setFinishing(true);
    setCompletionError("");
    try {
      await onComplete?.({ ...data });
      setCompleted(true);
    } catch (error) {
      setCompletionError(
        error instanceof Error
          ? error.message
          : "We couldn't complete setup. Please try again.",
      );
    } finally {
      setFinishing(false);
    }
  }

  return (
    <div className="onb">
    <div className="page">
      <section className="onboarding-card" aria-label="ScanSafe onboarding">
        <header className="brand-row">
          <div className="brand">
            <span className="brand-mark">
              <Icon name="shield" size={22} />
            </span>
            <span className="brand-name">scansafe</span>
          </div>
          <button
            className="help-button"
            type="button"
            onClick={() => setHelpOpen(true)}
            aria-haspopup="dialog"
          >
            <Icon name="help" size={17} />
            <span>Help</span>
          </button>
        </header>

        <div className="progress-heading">
          <span>Step {step} of 3</span>
          <span>{step === 1 ? "About you" : step === 2 ? "Your location" : "Wallet"}</span>
        </div>
        <div
          className="progress-track"
          role="progressbar"
          aria-label="Onboarding progress"
          aria-valuemin={1}
          aria-valuemax={3}
          aria-valuenow={step}
        >
          <span style={{ width: `${(step / 3) * 100}%` }} />
        </div>

        {step === 1 && (
          <form className="step-content profile-step" onSubmit={continueFromProfile}>
            <div className="step-icon">
              <Icon name="user" size={23} />
            </div>
            <h1>Let’s get you set up</h1>
            <p className="intro">
              Tell us a little about yourself to create your secure ScanSafe profile.
            </p>

            <div className="fields">
              <label className="field">
                <span>Full name</span>
                <span className="input-wrap">
                  <Icon name="user" size={17} />
                  <input
                    autoComplete="name"
                    name="fullName"
                    type="text"
                    placeholder="e.g. Maria Johnson"
                    minLength={2}
                    required
                    value={data.fullName}
                    onChange={(event) => updateProfile("fullName", event.target.value)}
                  />
                </span>
              </label>

              <label className="field">
                <span>Email address</span>
                <span className="input-wrap">
                  <Icon name="mail" size={17} />
                  <input
                    autoComplete="email"
                    name="email"
                    type="email"
                    placeholder="maria@example.com"
                    required
                    value={data.email}
                    onChange={(event) => updateProfile("email", event.target.value)}
                  />
                </span>
              </label>

              <label className="field">
                <span>Mobile number</span>
                <span className="input-wrap">
                  <Icon name="phone" size={17} />
                  <input
                    autoComplete="tel"
                    name="phone"
                    type="tel"
                    placeholder="+1 (555) 123-4567"
                    required
                    value={data.phone}
                    onChange={(event) => {
                      const value = event.currentTarget.value;
                      const digits = value.replace(/\D/g, "");
                      event.currentTarget.setCustomValidity(
                        value && digits.length < 7
                          ? "Enter a phone number with at least 7 digits."
                          : "",
                      );
                      updateProfile("phone", value);
                    }}
                  />
                </span>
              </label>
            </div>

            <label className="consent">
              <input
                type="checkbox"
                checked={data.facetimeOk}
                onChange={(event) =>
                  setData((current) => ({ ...current, facetimeOk: event.target.checked }))
                }
              />
              <span>
                <strong>ScanSafe can FaceTime me</strong> to show me what a code opens, live,
                before I tap it.
                <small>Text “hi” to +1 (650) 444-4331 once from this phone so we can reach you.</small>
              </span>
            </label>

            <p className="privacy-note">
              <Icon name="lock" size={16} />
              <span>Saved only on this phone. We only use your number if you ask us to FaceTime you.</span>
            </p>

            <button className="primary-button profile-continue" type="submit">
              <span>Continue</span>
              <Icon name="arrow-right" size={18} />
            </button>
            <SecurityFooter />
          </form>
        )}

        {step === 2 && (
          <div className="step-content location-step">
            <div className="step-icon">
              <Icon name="location" size={23} />
            </div>
            <h1>Confirm your location</h1>
            <p className="intro">
              Share your rough location so ScanSafe can warn people nearby about scam QR
              codes, like fake parking meters.
            </p>

            <section className="location-panel" aria-labelledby="location-title">
              <div className="location-art" aria-hidden="true">
                <span className="location-ring ring-outer" />
                <span className="location-ring ring-inner" />
                <span className="target-badge">
                  <Icon name="target" size={28} />
                </span>
              </div>
              <h2 id="location-title">
                {data.location ? "Location captured" : "Allow location access"}
              </h2>
              <p>
                {data.location
                  ? "Your location is ready. You can continue or update it."
                  : "Your browser will ask for permission. Choose “Allow” to continue."}
              </p>
              <button
                type="button"
                className="primary-button location-button"
                onClick={useMyLocation}
                disabled={locationLoading}
              >
                {locationLoading ? (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    <span>Requesting location…</span>
                  </>
                ) : (
                  <>
                    <Icon name="target" size={17} />
                    <span>{data.location ? "Update my location" : "Use my location"}</span>
                  </>
                )}
              </button>
            </section>

            {locationError && (
              <p className="inline-error" role="alert">
                {locationError}
              </p>
            )}

            <p className="privacy-note location-privacy">
              <Icon name="lock" size={17} />
              <span>
                <strong>You’re in control.</strong> We round it to about 100 meters and
                only send it when you check a code.
              </span>
            </p>

            <button
              className="primary-button location-continue"
              type="button"
              disabled={!data.location}
              onClick={() => setStep(3)}
            >
              <span>Continue</span>
              <Icon name="arrow-right" size={18} />
            </button>
            <button
              className="text-button back-button"
              type="button"
              onClick={() => {
                setData((current) => ({ ...current, location: null }));
                setStep(3);
              }}
            >
              <span>Not now, skip this step</span>
            </button>
            <button className="text-button back-button" type="button" onClick={() => setStep(1)}>
              <Icon name="back" size={17} />
              <span>Back</span>
            </button>
            <SecurityFooter />
          </div>
        )}

        {step === 3 && (
          <div className="step-content wallet-step">
            <div className="step-icon">
              <Icon name="wallet" size={23} />
            </div>
            <h1>Connect a wallet</h1>
            <p className="intro">
              You can connect a Solana wallet for future ScanSafe features, or simply
              skip this step.
            </p>

            <section className="wallet-panel" aria-labelledby="wallet-title">
              <div className="wallet-art" aria-hidden="true">
                <span className="wallet-art-back" />
                <span className="wallet-art-front">
                  <i />
                  <i />
                  <i />
                </span>
              </div>
              <h2 id="wallet-title">Solana wallet</h2>
              <p>Securely connect Phantom or another supported wallet.</p>
              <button
                type="button"
                className="wallet-select"
                onClick={() =>
                  setWalletMessage("Wallet connection isn’t available yet. You can skip this step.")
                }
              >
                Select Wallet
              </button>
              <span className="optional-label">Optional — not required</span>
            </section>
            {walletMessage && (
              <p className="wallet-message" role="status">
                {walletMessage}
              </p>
            )}

            <p className="privacy-note wallet-privacy">
              <Icon name="shield" size={18} />
              <span>
                <strong>Your wallet stays yours.</strong> ScanSafe cannot access your
                funds or approve transactions for you.
              </span>
            </p>

            <button
              className="primary-button finish-button"
              type="button"
              onClick={finishOnboarding}
              disabled={finishing || completed}
            >
              <span>
                {completed ? "Setup complete" : finishing ? "Finishing…" : "Skip and finish"}
              </span>
              {!completed && <Icon name="arrow-right" size={18} />}
            </button>
            {completionError && (
              <p className="inline-error completion-error" role="alert">
                {completionError}
              </p>
            )}
            {completed && (
              <p className="completion-message" role="status">
                You’re all set. Your details are ready for ScanSafe.
              </p>
            )}
            <button className="text-button back-button" type="button" onClick={() => setStep(2)}>
              <Icon name="back" size={17} />
              <span>Back</span>
            </button>
            <SecurityFooter />
          </div>
        )}
      </section>

      {helpOpen && (
        <div className="dialog-backdrop" onMouseDown={() => setHelpOpen(false)}>
          <section
            className="help-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="help-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button
              className="dialog-close"
              type="button"
              onClick={() => setHelpOpen(false)}
              aria-label="Close help"
            >
              ×
            </button>
            <h2 id="help-title">About setup</h2>
            <p>
              Add your contact details, choose whether to share your rough location,
              and skip the optional wallet step if you prefer. Everything is saved only
              on this phone.
            </p>
            <p>Your wallet is not connected during this setup.</p>
          </section>
        </div>
      )}
    </div>
    </div>
  );
}

function SecurityFooter() {
  return (
    <p className="security-footer">
      <Icon name="shield" size={14} />
      <span>Protected by ScanSafe security</span>
    </p>
  );
}

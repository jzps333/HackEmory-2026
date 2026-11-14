"use client";

import { useState, type FormEvent } from "react";
import { Icon } from "@/components/Icon";
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
      const location = await requestCurrentLocation();
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
    <main className="page">
      <aside className="welcome-panel" aria-hidden="true">
        <div className="welcome-brand">
          <span className="brand-mark">
            <Icon name="shield" size={22} />
          </span>
          <span>ScanSafe</span>
        </div>
        <div className="welcome-copy">
          <span className="eyebrow">Before your next scan</span>
          <h1>Check a QR code before you open it.</h1>
          <p>
            QR links can disguise where they lead. Set up your ScanSafe profile before
            your next scan.
          </p>
        </div>
        <div className="welcome-art">
          <span className="art-orb art-orb-large" />
          <span className="art-orb art-orb-small" />
          <div className="location-float">
            <span className="float-icon"><Icon name="location" size={18} /></span>
            <span><strong>Right where you are</strong><small>Your safety, your way</small></span>
            <span className="online-dot" />
          </div>
          <div className="privacy-float">
            <span className="privacy-check"><Icon name="shield" size={16} /></span>
            <span><strong>Private by design</strong><small>Your details stay yours</small></span>
          </div>
        </div>
        <p className="welcome-footnote"><span /> Here for the moments that matter</p>
      </aside>

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

            <p className="privacy-note">
              <Icon name="lock" size={16} />
              <span>Your details are encrypted and kept private.</span>
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
              ScanSafe uses your precise coordinates to give you accurate local safety
              information.
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
                <strong>You’re in control.</strong> We only use this location to
                personalize ScanSafe for you.
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
              Add your contact details, choose whether to share your device location,
              and skip the optional wallet step if you prefer.
            </p>
            <p>Your wallet is not connected during this setup.</p>
          </section>
        </div>
      )}
    </main>
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

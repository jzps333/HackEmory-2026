"use client";

import { useState, type FormEvent } from "react";
import { DeviceStatusBar } from "@/components/DeviceStatusBar";
import type { OnboardingCompletionHandler, OnboardingData } from "@/lib/onboarding";

const prompts = [
  {
    label: "What should we call you?",
    title: "Let’s start with your name.",
    field: "firstName",
    firstName: true,
  },
  {
    label: "Where can we reach you?",
    title: "Let’s start with your email.",
    field: "email",
  },
  {
    label: "What’s your phone number?",
    title: "Add your phone number.",
    field: "phone",
  },
] as const;

export function OnboardingFlow({
  onComplete,
}: {
  onComplete: OnboardingCompletionHandler;
}) {
  const [step, setStep] = useState(0);
  const [data, setData] = useState<OnboardingData>({
    firstName: "",
    lastName: "",
    email: "",
    phone: "",
  });
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    if (step === 0 && (!data.firstName.trim() || !data.lastName.trim())) {
      setError("Add both your first and last name.");
      return;
    }
    if (step === 2) {
      const digits = data.phone.replace(/\D/g, "").length;
      if (digits < 7 || digits > 15) {
        setError("Enter a phone number with 7 to 15 digits.");
        return;
      }
    }
    setError("");
    if (step < prompts.length - 1) {
      setStep((current) => current + 1);
      return;
    }

    try {
      await onComplete({
        firstName: data.firstName.trim(),
        lastName: data.lastName.trim(),
        email: data.email.trim(),
        phone: data.phone.trim(),
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "We couldn’t save your details. Please try again.");
    }
  }

  const prompt = prompts[step];
  return (
    <main className="app-shell onboarding-shell">
      <DeviceStatusBar />
      <header className="topbar">
        <span className="wordmark"><span className="brand-icon" aria-hidden="true">S</span>ScanSafe</span>
        <span className="topbar-note">A little more peace of mind</span>
      </header>
      <section className="onboarding-card">
        <div className="step-count">A FEW QUICK DETAILS <span>{step + 1} of 3</span></div>
        <div className="progress-track" aria-label={`Step ${step + 1} of 3`}>
          <span style={{ width: `${((step + 1) / prompts.length) * 100}%` }} />
        </div>
        <form className="onboarding-content" onSubmit={submit}>
          <span className="eyebrow">{prompt.label}</span>
          <h1>{prompt.title}</h1>
          <p className="supporting-copy">We’ll keep it simple and only use these details for your account.</p>
          {"firstName" in prompt ? (
            <div className="field-pair">
              <label className="field">
                <span>First name</span>
                <input
                  autoComplete="given-name"
                  autoFocus
                  required
                  value={data.firstName}
                  onChange={(event) => setData({ ...data, firstName: event.target.value })}
                  placeholder="First name"
                />
              </label>
              <label className="field">
                <span>Last name</span>
                <input
                  autoComplete="family-name"
                  required
                  value={data.lastName}
                  onChange={(event) => setData({ ...data, lastName: event.target.value })}
                  placeholder="Last name"
                />
              </label>
            </div>
          ) : prompt.field === "email" ? (
            <label className="field">
              <span>Email address</span>
              <input
                autoComplete="email"
                autoFocus
                type="email"
                required
                value={data.email}
                onChange={(event) => setData({ ...data, email: event.target.value })}
                placeholder="you@example.com"
              />
            </label>
          ) : (
            <label className="field">
              <span>Phone number</span>
              <input
                autoComplete="tel"
                autoFocus
                type="tel"
                required
                value={data.phone}
                onChange={(event) => setData({ ...data, phone: event.target.value })}
                placeholder="(555) 123-4567"
              />
            </label>
          )}
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="primary-button full-button" type="submit">
            {step === prompts.length - 1 ? "Continue" : "Next"}
          </button>
          <p className="privacy-note">Your details stay on this device for this demo.</p>
        </form>
      </section>
    </main>
  );
}

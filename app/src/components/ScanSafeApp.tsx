"use client";

import { useEffect, useState } from "react";
import { BottomNav, type MainTab } from "@/components/BottomNav";
import { Dashboard } from "@/components/Dashboard";
import { DeviceStatusBar } from "@/components/DeviceStatusBar";
import { DurationPicker } from "@/components/DurationPicker";
import { LocationPermission } from "@/components/LocationPermission";
import { OnboardingFlow } from "@/components/OnboardingFlow";
import { ParkingConfirmation } from "@/components/ParkingConfirmation";
import { ParkingLots } from "@/components/ParkingLots";
import { Profile } from "@/components/Profile";
import { ScanResult } from "@/components/ScanResult";
import { Scanner } from "@/components/Scanner";
import { VehicleSelect } from "@/components/VehicleSelect";
import { Verify } from "@/components/Verify";
import { WalletSetup } from "@/components/WalletSetup";
import type {
  AppData,
  ParkingLot,
  ParkingSession,
  Vehicle,
} from "@/lib/appStorage";
import type { Coordinates, OnboardingData } from "@/lib/onboarding";
import {
  checkUrl,
  createAppData,
  createParkingSession,
  loadAppData,
  saveAppData,
  verifyDemoCode,
  type ScanResult as ScanResultData,
} from "@/services/appServices";

type Screen =
  | "loading"
  | "onboarding"
  | "wallet"
  | "location"
  | "home"
  | "scanner"
  | "result"
  | "parking-lots"
  | "vehicle"
  | "duration"
  | "verify"
  | "confirmation"
  | "profile";

const mainTabs: MainTab[] = ["home", "scan", "parking", "profile"];

function activeTab(screen: Screen): MainTab {
  if (screen === "scanner" || screen === "result") return "scan";
  if (screen === "profile") return "profile";
  if (["parking-lots", "vehicle", "duration", "verify", "confirmation"].includes(screen)) return "parking";
  return "home";
}

export function ScanSafeApp() {
  const [data, setData] = useState<AppData | null>(null);
  const [screen, setScreen] = useState<Screen>("loading");
  const [draftUser, setDraftUser] = useState<OnboardingData | null>(null);
  const [scanResult, setScanResult] = useState<ScanResultData | null>(null);
  const [scanFeedback, setScanFeedback] = useState("");
  const [preferredLot, setPreferredLot] = useState<ParkingLot | null>(null);
  const [selectedLot, setSelectedLot] = useState<ParkingLot | null>(null);
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle | null>(null);
  const [durationMinutes, setDurationMinutes] = useState(60);
  const [activeSession, setActiveSession] = useState<ParkingSession | null>(null);
  const [storageMessage, setStorageMessage] = useState("");
  const [parkingFromScan, setParkingFromScan] = useState(false);

  useEffect(() => {
    try {
      const saved = loadAppData(window.localStorage);
      setData(saved);
      setScreen(saved ? "home" : "onboarding");
    } catch (error) {
      setStorageMessage(
        error instanceof Error
          ? error.message
          : "Saved data could not be read. You can continue, but it may not be saved.",
      );
      setScreen("onboarding");
    }
  }, []);

  function persist(next: AppData) {
    setData(next);
    try {
      saveAppData(window.localStorage, next);
      setStorageMessage("");
    } catch (error) {
      setStorageMessage(
        error instanceof Error
          ? `This visit is still available, but we couldn’t save it: ${error.message}`
          : "This visit is still available, but we couldn’t save it on this device.",
      );
    }
  }

  function finishOnboarding(user: OnboardingData) {
    setDraftUser(user);
    setScreen("wallet");
  }

  function finishLocation(location: Coordinates | null) {
    if (!draftUser) {
      setScreen("onboarding");
      return;
    }
    persist(createAppData(draftUser, location));
    setDraftUser(null);
    setScreen("home");
  }

  function scan(value: string) {
    try {
      setScanResult(checkUrl(value));
      setScanFeedback("");
      setScreen("result");
    } catch (error) {
      setScanFeedback(error instanceof Error ? error.message : "We couldn’t check that link.");
      setScreen("scanner");
    }
  }

  function openParking(lot: ParkingLot | null, fromScan: boolean) {
    setPreferredLot(lot);
    setSelectedLot(lot);
    setParkingFromScan(fromScan);
    setScreen("parking-lots");
  }

  function navigate(tab: MainTab) {
    if (!mainTabs.includes(tab)) return;
    setScanFeedback("");
    if (tab === "home") setScreen("home");
    if (tab === "scan") setScreen("scanner");
    if (tab === "parking") openParking(null, false);
    if (tab === "profile") setScreen("profile");
  }

  function goBack() {
    const previous: Partial<Record<Screen, Screen>> = {
      scanner: "home",
      result: "scanner",
      "parking-lots": parkingFromScan ? "result" : "home",
      vehicle: "parking-lots",
      duration: "vehicle",
      verify: "duration",
      confirmation: "home",
      profile: "home",
    };
    const target = previous[screen];
    if (target) setScreen(target);
    if (screen === "parking-lots" && !parkingFromScan) setPreferredLot(null);
  }

  if (screen === "loading") {
    return <main className="app-shell loading-shell"><span className="loading-spinner" />Getting things ready…</main>;
  }
  if (screen === "onboarding") return <OnboardingFlow onComplete={finishOnboarding} />;
  if (screen === "wallet") return <WalletSetup onSkip={() => setScreen("location")} />;
  if (screen === "location") return <LocationPermission onComplete={finishLocation} />;

  const currentTab = activeTab(screen);
  const showBack = screen !== "home";
  const currentName = data?.user.firstName || "there";

  return (
    <div className="app-shell">
      <DeviceStatusBar />
      <header className="topbar app-topbar">
        {showBack ? (
          <button type="button" className="back-button" onClick={goBack} aria-label="Go back">‹ <span>Back</span></button>
        ) : (
          <span className="topbar-note">A little more peace of mind</span>
        )}
        <span className="wordmark"><span className="brand-icon" aria-hidden="true">S</span>ScanSafe</span>
        <span className="topbar-greeting">{screen === "home" ? `Hi, ${currentName}` : ""}</span>
      </header>
      {storageMessage && <p className="storage-banner" role="status">{storageMessage}</p>}
      <main className="screen-stage" key={screen}>
        {screen === "home" && data && (
          <Dashboard
            firstName={currentName}
            latestSession={data.sessions.at(-1) ?? null}
            onScan={() => setScreen("scanner")}
            onParking={() => openParking(null, false)}
            onViewAll={() => setScreen("profile")}
          />
        )}
        {screen === "scanner" && (
          <Scanner
            onResult={scan}
            onClose={() => setScreen("home")}
            feedback={scanFeedback}
          />
        )}
        {screen === "result" && scanResult && (
          <ScanResult
            result={scanResult}
            onContinueParking={() => openParking(scanResult.parkingLot, true)}
            onScanAgain={() => {
              setScanFeedback("");
              setScreen("scanner");
            }}
          />
        )}
        {screen === "parking-lots" && (
          <ParkingLots
            preferredLot={preferredLot}
            onSelect={(lot) => {
              setSelectedLot(lot);
              setScreen("vehicle");
            }}
          />
        )}
        {screen === "vehicle" && data && (
          <VehicleSelect
            vehicles={data.vehicles}
            selectedVehicleId={selectedVehicle?.id ?? ""}
            onAdd={(vehicle) => persist({ ...data, vehicles: [...data.vehicles, vehicle] })}
            onContinue={(vehicle) => {
              setSelectedVehicle(vehicle);
              setScreen("duration");
            }}
          />
        )}
        {screen === "duration" && selectedLot && selectedVehicle && (
          <DurationPicker
            lot={selectedLot}
            vehicle={selectedVehicle}
            onContinue={(minutes) => {
              setDurationMinutes(minutes);
              setScreen("verify");
            }}
          />
        )}
        {screen === "verify" && data && selectedLot && selectedVehicle && (
          <Verify
            phone={data.user.phone}
            onVerify={(code) => {
              if (!verifyDemoCode(code)) return false;
              const session = createParkingSession(selectedLot, selectedVehicle, durationMinutes);
              persist({ ...data, sessions: [...data.sessions, session] });
              setActiveSession(session);
              setScreen("confirmation");
              return true;
            }}
          />
        )}
        {screen === "confirmation" && activeSession && (
          <ParkingConfirmation
            session={activeSession}
            onDone={() => {
              setActiveSession(null);
              setScreen("home");
            }}
          />
        )}
        {screen === "profile" && data && <Profile data={data} />}
      </main>
      <BottomNav active={currentTab} onNavigate={navigate} />
    </div>
  );
}

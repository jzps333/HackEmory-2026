import type {
  AppData,
  ParkingLot,
  ParkingSession,
  Vehicle,
  VehicleType,
} from "@/lib/appStorage";
import type { Coordinates, OnboardingData } from "@/lib/onboarding";

export type ScanRisk = "safe" | "suspicious" | "malicious";

export interface ScanResult {
  url: string;
  hostname: string;
  risk: ScanRisk;
  reasons: string[];
  parkingLot: ParkingLot | null;
}

export const DEMO_SCAN_EXAMPLES = [
  { label: "Safe example", url: "https://example.com" },
  { label: "Suspicious example", url: "http://bit.ly/sample-link" },
  { label: "Malicious example", url: "https://paypa1-login.xyz/verify" },
  { label: "Parking QR example", url: "https://parking.example/lot/L1" },
];

export const PARKING_LOTS: ParkingLot[] = [
  { id: "L1", name: "Peachtree Garage", address: "210 Peachtree St NE", rate: 4.5 },
  { id: "L2", name: "Midtown Surface Lot", address: "88 10th St NW", rate: 3 },
  { id: "L3", name: "Decatur Square Deck", address: "101 E Court Sq", rate: 2.5 },
];

export const DEMO_VERIFICATION_CODE = "123456";
const STORAGE_KEY = "scansafe-app-v1";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isCoordinates(value: unknown): value is Coordinates {
  return (
    isRecord(value) &&
    typeof value.latitude === "number" &&
    typeof value.longitude === "number"
  );
}

function isUser(value: unknown): value is OnboardingData {
  return (
    isRecord(value) &&
    typeof value.firstName === "string" &&
    typeof value.lastName === "string" &&
    typeof value.email === "string" &&
    typeof value.phone === "string"
  );
}

function isVehicle(value: unknown): value is Vehicle {
  const allowedTypes = new Set<string>(["", "Car", "SUV", "Truck", "Motorcycle", "Other"]);
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.plate === "string" &&
    typeof value.nickname === "string" &&
    typeof value.type === "string" &&
    allowedTypes.has(value.type)
  );
}

function isParkingLot(value: unknown): value is ParkingLot {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.address === "string" &&
    typeof value.rate === "number"
  );
}

function isParkingSession(value: unknown): value is ParkingSession {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    isParkingLot(value.lot) &&
    isVehicle(value.vehicle) &&
    typeof value.durationMinutes === "number" &&
    typeof value.startedAt === "number" &&
    typeof value.endsAt === "number" &&
    typeof value.price === "number"
  );
}

function isAppData(value: unknown): value is AppData {
  return (
    isRecord(value) &&
    isUser(value.user) &&
    (value.location === null || isCoordinates(value.location)) &&
    Array.isArray(value.vehicles) &&
    value.vehicles.every(isVehicle) &&
    Array.isArray(value.sessions) &&
    value.sessions.every(isParkingSession)
  );
}

function migratePreviousAppData(value: unknown): AppData | null {
  if (!isRecord(value) || !isRecord(value.profile)) return null;
  const { profile } = value;
  if (
    typeof profile.fullName !== "string" ||
    typeof profile.email !== "string" ||
    typeof profile.phone !== "string" ||
    !Array.isArray(value.vehicles)
  ) {
    return null;
  }

  const [firstName = "", ...rest] = profile.fullName.trim().split(/\s+/);
  const vehicles: Vehicle[] = value.vehicles.flatMap((item) => {
    if (!isRecord(item) || typeof item.plate !== "string") return [];
    return [{
      id: typeof item.id === "string" ? item.id : `legacy-${item.plate}`,
      plate: item.plate,
      nickname: typeof item.name === "string" ? item.name : "",
      type: "",
    }];
  });

  const sessions: ParkingSession[] = [];
  if (isRecord(value.parkingSession)) {
    const previous = value.parkingSession;
    const startedAt = typeof previous.startedAt === "string"
      ? Date.parse(previous.startedAt)
      : Number.NaN;
    const endsAt = typeof previous.endsAt === "string"
      ? Date.parse(previous.endsAt)
      : Number.NaN;
    if (
      Number.isFinite(startedAt) &&
      Number.isFinite(endsAt) &&
      typeof previous.location === "string" &&
      typeof previous.vehicleName === "string" &&
      typeof previous.licensePlate === "string" &&
      typeof previous.estimatedPrice === "number"
    ) {
      const durationMinutes = Math.max(1, Math.round((endsAt - startedAt) / 60_000));
      const vehicle: Vehicle = {
        id: "legacy-session-vehicle",
        plate: previous.licensePlate,
        nickname: previous.vehicleName,
        type: "",
      };
      sessions.push({
        id: "legacy-session",
        lot: {
          id: "legacy",
          name: previous.location,
          address: "",
          rate: previous.estimatedPrice / (durationMinutes / 60),
        },
        vehicle,
        durationMinutes,
        startedAt,
        endsAt,
        price: previous.estimatedPrice,
      });
    }
  }

  return {
    user: {
      firstName,
      lastName: rest.join(" "),
      email: profile.email,
      phone: profile.phone,
    },
    location: isCoordinates(profile.location) ? profile.location : null,
    vehicles,
    sessions,
  };
}

export function loadAppData(storage: Storage): AppData | null {
  const saved = storage.getItem(STORAGE_KEY);
  if (!saved) return null;

  const value: unknown = JSON.parse(saved);
  if (isAppData(value)) return value;
  const migrated = migratePreviousAppData(value);
  if (migrated) return migrated;
  throw new Error("Saved ScanSafe data couldn’t be read. Clear this site’s local storage to restart.");
}

export function saveAppData(storage: Storage, data: AppData): void {
  storage.setItem(STORAGE_KEY, JSON.stringify(data));
}

export function createAppData(
  user: OnboardingData,
  location: Coordinates | null,
): AppData {
  return { user, location, vehicles: [], sessions: [] };
}

export function createVehicle(
  plate: string,
  nickname: string,
  type: VehicleType,
): Vehicle {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    plate: plate.trim().toUpperCase(),
    nickname: nickname.trim(),
    type,
  };
}

function findParkingLot(url: URL): ParkingLot | null {
  const isParking = /park|lot/i.test(`${url.hostname}${url.pathname}`) ||
    url.searchParams.has("lot");
  if (!isParking) return null;
  const lotId = url.searchParams.get("lot")?.toUpperCase() ??
    url.pathname.split("/").filter(Boolean).at(-1)?.toUpperCase();
  return PARKING_LOTS.find((lot) => lot.id === lotId) ?? PARKING_LOTS[0];
}

export function checkUrl(rawValue: string): ScanResult {
  let url: URL;
  try {
    url = new URL(rawValue.trim());
  } catch {
    throw new Error("Enter a complete link starting with https:// or http://.");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error("Only web links can be checked.");
  }
  if (url.username || url.password) {
    throw new Error("This link contains embedded sign-in details, so we can’t check it.");
  }

  const lowered = url.toString().toLowerCase();
  const reasons: string[] = [];
  let risk: ScanRisk = "safe";

  if (/^https?:\/\/\d{1,3}(?:\.\d{1,3}){3}/.test(lowered)) {
    reasons.push("The link points to a number address instead of a website name.");
    risk = "malicious";
  }
  if (/(paypa1|g00gle|arnazon)/.test(lowered)) {
    reasons.push("The name looks like it may imitate a well-known brand.");
    risk = "malicious";
  }
  if (/(login|verify|secure|account|wallet).*\.(xyz|top|click|ru)|\.(xyz|top|click)\b/.test(lowered)) {
    reasons.push("The address uses an ending often seen on throwaway sites.");
    risk = "malicious";
  }
  if (/(bit\.ly|tinyurl|t\.co|goo\.gl)/.test(lowered)) {
    reasons.push("A shortened link hides its final destination.");
    if (risk === "safe") risk = "suspicious";
  }
  if (url.protocol === "http:") {
    reasons.push("This site does not use an encrypted connection.");
    if (risk === "safe") risk = "suspicious";
  }

  const parkingLot = findParkingLot(url);
  if (reasons.length === 0) {
    reasons.push(
      parkingLot
        ? "This looks like a parking link. Check the lot details before continuing."
        : "Nothing unusual was found in this address. Still open it only if you expected this QR code.",
    );
  }

  return {
    url: url.toString(),
    hostname: url.hostname,
    risk,
    reasons,
    parkingLot,
  };
}

export function calculateParkingPrice(lot: ParkingLot, durationMinutes: number): number {
  return Math.round((lot.rate * durationMinutes / 60) * 100) / 100;
}

export function verifyDemoCode(value: string): boolean {
  // TODO: Replace with a server-side verification provider. Never send a real SMS from this demo.
  return value === DEMO_VERIFICATION_CODE;
}

export function createParkingSession(
  lot: ParkingLot,
  vehicle: Vehicle,
  durationMinutes: number,
  startedAt = Date.now(),
): ParkingSession {
  return {
    id: `${startedAt}-${Math.random().toString(36).slice(2, 8)}`,
    lot,
    vehicle,
    durationMinutes,
    startedAt,
    endsAt: startedAt + durationMinutes * 60_000,
    price: calculateParkingPrice(lot, durationMinutes),
  };
}

// TODO: Replace this local rule set with a backend scan endpoint and evidence-backed findings.

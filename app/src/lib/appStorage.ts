import type { Coordinates, OnboardingData } from "@/lib/onboarding";

export type VehicleType = "Car" | "SUV" | "Truck" | "Motorcycle" | "Other" | "";

export interface Vehicle {
  id: string;
  plate: string;
  nickname: string;
  type: VehicleType;
}

export interface ParkingLot {
  id: string;
  name: string;
  address: string;
  rate: number;
}

export interface ParkingSession {
  id: string;
  lot: ParkingLot;
  vehicle: Vehicle;
  durationMinutes: number;
  startedAt: number;
  endsAt: number;
  price: number;
}

export interface AppData {
  user: OnboardingData;
  location: Coordinates | null;
  vehicles: Vehicle[];
  sessions: ParkingSession[];
}

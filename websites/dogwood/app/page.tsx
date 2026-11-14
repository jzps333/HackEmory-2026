import type { Metadata } from "next";
import AppClient from "./AppClient";

// Fictional brand (Dogwood Lot & Meter Co.) for the ScanSafe demo. Devnet test SOL only.
export const metadata: Metadata = {
  title: "Dogwood Parking",
  robots: { index: false, follow: false },
};

export default function DogwoodApp() {
  return <AppClient />;
}

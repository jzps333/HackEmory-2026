import type { Metadata } from "next";
import InstallClient from "./InstallClient";

// Fictional brand (Dogwood Lot & Meter Co.) for the ScanSafe demo. Not a real app store or app.
export const metadata: Metadata = {
  title: "Get Dogwood Parking",
  robots: { index: false, follow: false },
};

export default function DogwoodInstall() {
  return <InstallClient />;
}

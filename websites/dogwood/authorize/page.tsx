import type { Metadata } from "next";
import AuthorizeClient from "./AuthorizeClient";

// Fictional brand (Dogwood Lot & Meter Co.) for the ScanSafe demo: link ScanSafe to a Dogwood account.
export const metadata: Metadata = {
  title: "Dogwood Parking - Link ScanSafe",
  robots: { index: false, follow: false },
};

export default function DogwoodAuthorize() {
  return <AuthorizeClient />;
}

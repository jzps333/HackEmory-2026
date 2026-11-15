import type { Metadata } from "next";
import MapClient from "./MapClient";

export const metadata: Metadata = { title: "Scam map · ScanSafe" };

export default function MapPage() {
  return <MapClient />;
}

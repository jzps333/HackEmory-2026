import type { Metadata } from "next";
import DeskMap from "@/components/desktop/DeskMap";

export const metadata: Metadata = { title: "Scam map · ScanSafe" };

export default function DesktopMapPage() {
  return <DeskMap />;
}

import type { Metadata } from "next";
import DeskOnePage from "@/components/desktop/DeskOnePage";

export const metadata: Metadata = { title: "ScanSafe" };

export default function DesktopPage() {
  return <DeskOnePage />;
}

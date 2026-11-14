import type { Metadata } from "next";
import DeskStats from "@/components/desktop/DeskStats";

export const metadata: Metadata = { title: "Stats · ScanSafe" };

export default function DesktopStatsPage() {
  return <DeskStats />;
}

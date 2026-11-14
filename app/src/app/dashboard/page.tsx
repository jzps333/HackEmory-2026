import type { Metadata } from "next";
import DashboardClient from "./DashboardClient";

export const metadata: Metadata = { title: "Stats · ScanSafe" };

export default function DashboardPage() {
  return <DashboardClient />;
}

import type { Metadata } from "next";
import DeskHome from "@/components/desktop/DeskHome";

export const metadata: Metadata = { title: "ScanSafe" };

export default function DesktopHomePage() {
  return <DeskHome />;
}

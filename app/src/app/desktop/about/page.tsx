import type { Metadata } from "next";
import DeskAbout from "@/components/desktop/DeskAbout";

export const metadata: Metadata = {
  title: "About ScanSafe",
  description: "ScanSafe checks a link or QR code before you open it, on our own locked-down computer, and tells you in plain words.",
};

export default function DesktopAboutPage() {
  return <DeskAbout />;
}

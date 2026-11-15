import type { ReactNode } from "react";
import localFont from "next/font/local";
import DesktopShell from "@/components/desktop/DesktopShell";
import "./desktop.css";

// Fonts from GitHub, SIL Open Font License (licenses in ./fonts):
// Hubot Sans (github/hubot-sans) for headlines, Mona Sans (github/mona-sans) for text,
// Departure Mono (rektdeckard/departure-mono) for labels and numbers.
const display = localFont({
  src: [
    { path: "./fonts/HubotSansExpanded-ExtraBold.woff2", weight: "800" },
    { path: "./fonts/HubotSansExpanded-Black.woff2", weight: "900" },
  ],
  variable: "--font-display",
  display: "swap",
});
const body = localFont({ src: "./fonts/MonaSansVF-opsz-wght.woff2", weight: "200 900", variable: "--font-body", display: "swap" });
const mono = localFont({ src: "./fonts/DepartureMono-Regular.woff2", weight: "400", variable: "--font-mono", display: "swap" });

// Served to computers at the public URLs by src/proxy.ts. Phones never load this tree.
export default function DesktopLayout({ children }: { children: ReactNode }) {
  return (
    <div className={`desk ${display.variable} ${body.variable} ${mono.variable}`}>
      <DesktopShell>{children}</DesktopShell>
    </div>
  );
}

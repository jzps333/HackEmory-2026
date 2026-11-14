import type { ReactNode } from "react";
import DesktopShell from "@/components/desktop/DesktopShell";
import "./desktop.css";

// Served to computers at the public URLs by src/proxy.ts. Phones never load this tree.
export default function DesktopLayout({ children }: { children: ReactNode }) {
  return (
    <div className="desk">
      <DesktopShell>{children}</DesktopShell>
    </div>
  );
}

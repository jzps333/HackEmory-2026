import { redirect } from "next/navigation";

// Redirect-chain demo: a QR to /r/a hops /r/a -> /r/b -> the unpaid-toll scam, so ScanSafe can
// show every hop. Rendered per request so each hop is a real HTTP 307.
export const dynamic = "force-dynamic";
export const metadata = { robots: { index: false } };

export default function HopA() {
  redirect("/r/b");
}

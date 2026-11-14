import { redirect } from "next/navigation";

// Second hop of the redirect-chain demo (see /r/a).
export const dynamic = "force-dynamic";
export const metadata = { robots: { index: false } };

export default function HopB() {
  redirect("/websites/scams/unpaid-toll");
}

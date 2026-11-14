import type { Metadata } from "next";
import ScamOffer from "../../components/ScamOffer";

export const metadata: Metadata = { title: "Morrow Coffee Rewards - Claim Your Free Year", robots: { index: false } };

export default function MorrowRewardsScam() {
  return <ScamOffer brand="Morrow Coffee" color="#6b3f1d" headline="Claim your FREE year of coffee"
    prize="a free year of Morrow Coffee" deadline="09:58" />;
}

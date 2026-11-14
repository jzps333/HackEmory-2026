import type { Metadata } from "next";
import ScamOffer from "../../components/ScamOffer";

export const metadata: Metadata = { title: "Pixel Palace - You Won 500 Free Tokens", robots: { index: false } };

export default function PixelPrizeScam() {
  return <ScamOffer brand="Pixel Palace" color="#5b21b6" headline="You won 500 FREE game tokens!"
    prize="500 free Pixel Palace tokens" deadline="04:59" />;
}

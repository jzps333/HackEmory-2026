import type { Metadata } from "next";
import MyApps from "../_components/MyApps";

export const metadata: Metadata = { title: "My apps" };

export default function AppsPage() {
  return <MyApps />;
}

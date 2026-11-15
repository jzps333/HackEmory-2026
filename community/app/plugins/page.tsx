import type { Metadata } from "next";
import PluginsBrowser from "../_components/PluginsBrowser";

export const metadata: Metadata = { title: "Community plugins" };

export default function PluginsPage() {
  return <PluginsBrowser />;
}

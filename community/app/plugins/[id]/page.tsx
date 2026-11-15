import type { Metadata } from "next";
import PluginDetail from "../../_components/PluginDetail";

type Params = { params: Promise<{ id: string }> };

function safeDecode(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  return { title: safeDecode(id).slice(0, 40) };
}

export default async function PluginPage({ params }: Params) {
  const { id } = await params;
  return <PluginDetail id={safeDecode(id)} />;
}

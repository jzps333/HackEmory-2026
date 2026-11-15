import type { Metadata } from "next";
import MyAppDetail from "../../_components/MyAppDetail";

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
  return { title: `My apps · ${safeDecode(id).slice(0, 40)}` };
}

export default async function MyAppPage({ params }: Params) {
  const { id } = await params;
  return <MyAppDetail id={safeDecode(id)} />;
}

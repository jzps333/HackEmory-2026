import { Puzzle } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import PageHeader from "../_components/PageHeader";
import { STATIC_SECTIONS } from "../_components/nav";

export const dynamicParams = false;

export function generateStaticParams() {
  return Object.keys(STATIC_SECTIONS).map((section) => ({ section }));
}

type Params = { params: Promise<{ section: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { section } = await params;
  return { title: STATIC_SECTIONS[section]?.title ?? "Not found" };
}

export default async function StaticSection({ params }: Params) {
  const { section } = await params;
  const page = STATIC_SECTIONS[section];
  if (!page) notFound();

  return (
    <>
      <PageHeader title={page.title} subtitle={page.subtitle} />
      <section className="card empty">
        <div className="empty-title">Static page in this demo</div>
        <p className="muted">
          This is a look-alike of the {page.title} page. Only Community plugins works in the ScanSafe demo.
        </p>
        <Link href="/plugins" className="btn btn-secondary">
          <Puzzle size={15} strokeWidth={1.75} />
          Go to Community plugins
        </Link>
      </section>
    </>
  );
}

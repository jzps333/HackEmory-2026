"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Scan" },
  { href: "/map", label: "Scam map" },
  { href: "/dashboard", label: "Stats" },
  { href: "/cities", label: "Dense cities" },
  { href: "/websites", label: "Sample sites" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav aria-label="Main">
      <ul className="nav-list">
        {LINKS.map((l) => {
          const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
          return (
            <li key={l.href}>
              <Link href={l.href} className="nav-link" aria-current={active ? "page" : undefined}>
                {l.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

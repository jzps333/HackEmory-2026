"use client";

import { ArrowLeft, ChevronsUpDown, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { FOOTER_NOTE, NAV } from "./nav";

function Wordmark() {
  return (
    <span className="wordmark">
      <span className="wordmark-mark" aria-hidden="true">
        <span className="mark-orange" />
        <span className="mark-blue" />
      </span>
      <span className="wordmark-text">Chert</span>
    </span>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const [open, setOpen] = useState(false);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");

  return (
    <div className="shell">
      <header className="topbar">
        <Link href="/overview" className="topbar-brand">
          <Wordmark />
        </Link>
        <span className="topbar-project">Toolstone demo</span>
        <button
          type="button"
          className="icon-btn"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="sidebar"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <X size={18} /> : <Menu size={18} />}
        </button>
      </header>

      <div className={`overlay${open ? " show" : ""}`} onClick={() => setOpen(false)} aria-hidden="true" />

      <aside id="sidebar" className={`sidebar${open ? " open" : ""}`} aria-label="Console navigation">
        <div className="sidebar-head">
          <Link href="/overview" className="sidebar-brand">
            <Wordmark />
          </Link>
          <button type="button" className="icon-btn sidebar-close" aria-label="Close menu" onClick={() => setOpen(false)}>
            <X size={18} />
          </button>
        </div>

        <button type="button" className="project-switch" aria-label="Project: Toolstone demo, Free trial">
          <span className="project-avatar" aria-hidden="true">S</span>
          <span className="project-text">
            <span className="project-name">Toolstone demo</span>
            <span className="project-plan"> · Free trial</span>
          </span>
          <ChevronsUpDown size={15} className="muted-icon" />
        </button>

        <Link href="/overview" className="all-projects">
          <ArrowLeft size={14} />
          All projects
        </Link>

        <div className="nav-label">Project</div>
        <nav className="nav">
          {NAV.map(({ href, label, icon: Icon, badge }) => (
            <Link
              key={href}
              href={href}
              className={`nav-item${isActive(href) ? " active" : ""}`}
              aria-current={isActive(href) ? "page" : undefined}
            >
              <Icon size={16} strokeWidth={1.75} />
              <span className="nav-text">{label}</span>
              {badge ? <span className="nav-badge">{badge}</span> : null}
            </Link>
          ))}
        </nav>

        <div className="account">
          <span className="account-avatar" aria-hidden="true">D</span>
          <span className="account-text">
            <span className="account-name">Demo account</span>
            <span className="account-sub">Toolstone demo · Owner</span>
          </span>
        </div>
      </aside>

      <div className="main">
        <main className="content">{children}</main>
        <footer className="footer-note">{FOOTER_NOTE}</footer>
      </div>
    </div>
  );
}

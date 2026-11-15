import {
  BookOpen,
  Bot,
  CodeXml,
  CreditCard,
  LayoutGrid,
  MessageSquare,
  Phone,
  PhoneCall,
  Puzzle,
  Settings,
  type LucideIcon,
} from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon; badge?: string };

export const NAV: NavItem[] = [
  { href: "/overview", label: "Overview", icon: LayoutGrid },
  { href: "/lines", label: "Lines", icon: Phone, badge: "1" },
  { href: "/calls", label: "Calls", icon: PhoneCall },
  { href: "/messages", label: "Messages", icon: MessageSquare },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/developer", label: "Developer", icon: CodeXml },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/settings", label: "Members and settings", icon: Settings },
  { href: "/docs", label: "Quickstart and docs", icon: BookOpen },
  { href: "/plugins", label: "Community plugins", icon: Puzzle },
];

/** Static look-alike pages (everything except Overview and Community plugins). */
export const STATIC_SECTIONS: Record<string, { title: string; subtitle: string }> = {
  lines: { title: "Lines", subtitle: "Phone numbers your agents answer and call from." },
  calls: { title: "Calls", subtitle: "FaceTime and phone calls placed or answered by your agents." },
  messages: { title: "Messages", subtitle: "iMessage threads between your agents and contacts." },
  agents: { title: "Agents", subtitle: "How your agents talk, see and act on calls." },
  developer: { title: "Developer", subtitle: "API keys, webhooks and request logs." },
  billing: { title: "Billing", subtitle: "Your plan, usage and invoices." },
  settings: { title: "Members and settings", subtitle: "Who can open this project, and its settings." },
  docs: { title: "Quickstart and docs", subtitle: "Get a line, connect an agent and place your first call." },
};

export const FOOTER_NOTE =
  "Community plugins demo for EmoryHacks 2026, built with Chert's permission. Not the official Chert console.";

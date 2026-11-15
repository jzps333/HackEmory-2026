export type MainTab = "home" | "scan" | "parking" | "profile";

const tabs: { id: MainTab; label: string; glyph: string }[] = [
  { id: "home", label: "Home", glyph: "⌂" },
  { id: "scan", label: "Scan", glyph: "▦" },
  { id: "parking", label: "Parking", glyph: "P" },
  { id: "profile", label: "Profile", glyph: "◯" },
];

export function BottomNav({
  active,
  onNavigate,
}: {
  active: MainTab;
  onNavigate: (tab: MainTab) => void;
}) {
  return (
    <nav className="bottom-nav" aria-label="Main navigation">
      {tabs.map((tab) => (
        <button
          type="button"
          key={tab.id}
          className={active === tab.id ? "active" : ""}
          aria-current={active === tab.id ? "page" : undefined}
          onClick={() => onNavigate(tab.id)}
        >
          <span aria-hidden="true">{tab.glyph}</span>
          <small>{tab.label}</small>
        </button>
      ))}
    </nav>
  );
}

// Which version of the site a request gets: the phone site (the existing pages) or the desktop site
// (one long page at app/desktop). Used by proxy.ts. No imports, so `node --test tests/` can run it directly.

export type View = "desktop" | "phone";
export type Section = "top" | "map" | "stats" | "about";

/** Public URL -> the desktop page that serves it (all of them: the desktop site is one long page). */
export const DESKTOP_PATHS: Record<string, string> = {
  "/": "/desktop",
  "/map": "/desktop",
  "/dashboard": "/desktop",
  "/about": "/desktop",
};

const SECTIONS: Record<string, Section> = { "/map": "map", "/dashboard": "stats", "/about": "about" };

const MOBILE_UA = /Mobi|Android|iPhone|iPod|iPad|Silk|Kindle|Opera Mini/i;

function asView(value: string | null): View | null {
  return value === "desktop" || value === "phone" ? value : null;
}

/** `?view=` wins, then the saved `ss_view` cookie, then the user agent. Unknown agents get the phone site. */
export function pickView(input: { ua: string | null; query: string | null; cookie: string | null }): View {
  const forced = asView(input.query) ?? asView(input.cookie);
  if (forced) return forced;
  if (!input.ua) return "phone";
  return MOBILE_UA.test(input.ua) ? "phone" : "desktop";
}

/** The section of the one-page desktop site that a public URL should open at. */
export function sectionFor(pathname: string): Section {
  return SECTIONS[pathname] ?? "top";
}

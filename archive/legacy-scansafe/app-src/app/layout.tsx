import type { Metadata, Viewport } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "ScanSafe",
  description: "Check a QR code for scams before you open it. We open it safely on our server first.",
  applicationName: "ScanSafe",
  // "default" = a solid light status bar above our white header (dark clock text stays readable) when
  // opened from the Home Screen. black-translucent would put white text over the white header.
  appleWebApp: { capable: true, title: "ScanSafe", statusBarStyle: "default" },
  // Next only emits mobile-web-app-capable; older iOS still looks for the apple- name to open full screen.
  other: { "apple-mobile-web-app-capable": "yes" },
  // Stop iOS from turning phone numbers, dates and amounts into blue links.
  formatDetection: { telephone: false, date: false, address: false, email: false },
  icons: {
    icon: [{ url: "/favicon.png", sizes: "32x32", type: "image/png" }, { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#514082",
  width: "device-width",
  initialScale: 1,
  // Lets the page use the full screen on notched iPhones; header/main pad themselves with env(safe-area-inset-*).
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">Skip to main content</a>
        <header className="site-header">
          <div className="site-brand" aria-label="ScanSafe">
            <span className="site-brand-mark" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" focusable="false">
                <path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            </span>
            <span className="site-brand-name">ScanSafe</span>
          </div>
          <Nav />
        </header>
        <main id="main" tabIndex={-1}>{children}</main>
      </body>
    </html>
  );
}

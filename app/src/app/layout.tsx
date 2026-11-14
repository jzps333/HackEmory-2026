import type { Metadata, Viewport } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "ScanSafe",
  description: "Check a QR code for scams before you open it. We open it safely on our server first.",
  applicationName: "ScanSafe",
  appleWebApp: { capable: true, title: "ScanSafe", statusBarStyle: "default" },
  icons: {
    icon: [{ url: "/favicon.png", sizes: "32x32", type: "image/png" }, { url: "/icons/icon-192.png", sizes: "192x192" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#0b3d2e",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">Skip to main content</a>
        <header className="site-header">
          <div className="brand" aria-label="ScanSafe">
            <img src="/icons/icon-192.png" alt="" width={36} height={36} />
            <span>ScanSafe</span>
          </div>
          <Nav />
        </header>
        <main id="main" tabIndex={-1}>{children}</main>
      </body>
    </html>
  );
}

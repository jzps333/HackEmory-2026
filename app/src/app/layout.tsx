import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'ScanSafe Factory', description: 'Build, run and share capabilities for your Chert assistant.' };
export default function Layout({children}: {children: React.ReactNode}) {
  return <html lang="en"><body><a className="skip" href="#main">Skip to workspace</a><header><a href="/">◈ ScanSafe <strong>Factory</strong></a><span>Built for Chert · Template preview</span></header><main id="main">{children}</main><footer>Reusable capabilities. Explicit permissions. Versions you control.</footer></body></html>;
}

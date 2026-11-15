import AuthProvider from "../_components/AuthProvider";

// One sign-in state for /apps and /apps/[id], kept while moving between them.
export default function AppsLayout({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

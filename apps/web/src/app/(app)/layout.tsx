import { AppShell } from "@/components/shell/app-shell";
import { requireSession } from "@/lib/session-context";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, organization, roles } = await requireSession();

  return (
    <AppShell user={user} organization={organization} roles={roles}>
      {children}
    </AppShell>
  );
}

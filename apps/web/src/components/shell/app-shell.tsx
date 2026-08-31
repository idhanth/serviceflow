"use client";

import { Menu } from "lucide-react";
import { useState } from "react";

import { RealtimeProvider } from "@/components/providers/realtime-provider";
import { ConnectionStatus } from "@/components/shell/connection-status";
import { GlobalSearch } from "@/components/shell/global-search";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { SidebarNav } from "@/components/shell/sidebar";
import { UserMenu } from "@/components/shell/user-menu";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import type { Organization, Role, SessionUser } from "@/lib/types";

interface AppShellProps {
  user: SessionUser;
  organization: Organization;
  roles: Role[];
  children: React.ReactNode;
}

function OrganizationBadge({ organization }: { organization: Organization }) {
  return (
    <div className="flex items-center gap-2.5 px-1">
      <div className="flex size-6 shrink-0 items-center justify-center rounded bg-primary text-[11px] font-semibold text-primary-foreground">
        {organization.name.slice(0, 1)}
      </div>
      <p className="min-w-0 truncate text-[13px] font-medium">{organization.name}</p>
    </div>
  );
}

export function AppShell({ user, organization, roles, children }: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const primaryRole = roles.includes("ADMIN") ? "ADMIN" : (roles[0] ?? "CUSTOMER");

  return (
    <RealtimeProvider>
    <div className="min-h-svh bg-background">
      {/* Desktop sidebar. 232px: wide enough for the longest label, narrow
          enough that the working area keeps the screen. */}
      <aside className="fixed inset-y-0 left-0 hidden w-[232px] flex-col border-r bg-sidebar lg:flex">
        <div className="flex h-12 items-center border-b px-3">
          <OrganizationBadge organization={organization} />
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-4">
          <SidebarNav roles={roles} />
        </div>
        <div className="border-t p-2">
          <UserMenu user={user} role={primaryRole} />
        </div>
      </aside>

      <div className="lg:pl-[232px]">
        {/* Utility bar: search on the left because it is the fastest way into
            anything, status and notifications on the right. Same 48px height as
            the sidebar header, so the two line up across the seam. */}
        <div className="sticky top-0 z-20 hidden h-12 items-center gap-3 border-b bg-background/85 px-6 backdrop-blur lg:flex">
          {roles.includes("ADMIN") ? (
            <div className="w-full max-w-sm">
              <GlobalSearch />
            </div>
          ) : (
            <span className="text-[13px] text-muted-foreground">{organization.name}</span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <ConnectionStatus />
            <NotificationBell />
          </div>
        </div>

        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b bg-background/90 px-3 backdrop-blur lg:hidden">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger
              render={<Button variant="ghost" size="icon" aria-label="Open navigation" />}
            >
              <Menu className="size-5" aria-hidden />
            </SheetTrigger>
            <SheetContent side="left" className="w-[264px] p-0">
              <SheetHeader className="flex h-12 justify-center border-b px-3">
                <SheetTitle className="sr-only">Navigation</SheetTitle>
                <OrganizationBadge organization={organization} />
              </SheetHeader>
              <div className="px-3 py-4">
                <SidebarNav roles={roles} onNavigate={() => setMobileOpen(false)} />
              </div>
              <div className="mt-auto border-t p-2">
                <UserMenu user={user} role={primaryRole} />
              </div>
            </SheetContent>
          </Sheet>
          <span className="flex-1 truncate text-[13px] font-medium">{organization.name}</span>
          <ConnectionStatus />
          <NotificationBell />
        </header>

        {/* One page frame for the whole product: the same gutters and the same
            top offset on every screen. */}
        <main className="mx-auto w-full max-w-[1360px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
          {children}
        </main>
      </div>
    </div>
    </RealtimeProvider>
  );
}

"use client";

import { Menu } from "lucide-react";
import { useState } from "react";

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
    <div className="flex items-center gap-3 px-2 py-1">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground">
        {organization.name.slice(0, 1)}
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold">{organization.name}</p>
        <p className="truncate text-xs text-muted-foreground">ServiceFlow</p>
      </div>
    </div>
  );
}

export function AppShell({ user, organization, roles, children }: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const primaryRole = roles.includes("ADMIN") ? "ADMIN" : (roles[0] ?? "CUSTOMER");

  return (
    <div className="min-h-svh bg-muted/30">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r bg-background lg:flex">
        <div className="p-3">
          <OrganizationBadge organization={organization} />
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-2">
          <SidebarNav roles={roles} />
        </div>
        <div className="border-t p-2">
          <UserMenu user={user} role={primaryRole} />
        </div>
      </aside>

      <div className="lg:pl-64">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b bg-background/95 px-4 py-3 backdrop-blur lg:hidden">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger
              render={<Button variant="ghost" size="icon" aria-label="Open navigation" />}
            >
              <Menu className="size-5" aria-hidden />
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-0">
              <SheetHeader className="p-3 pb-0">
                <SheetTitle className="sr-only">Navigation</SheetTitle>
                <OrganizationBadge organization={organization} />
              </SheetHeader>
              <div className="px-3 py-2">
                <SidebarNav roles={roles} onNavigate={() => setMobileOpen(false)} />
              </div>
              <div className="mt-auto border-t p-2">
                <UserMenu user={user} role={primaryRole} />
              </div>
            </SheetContent>
          </Sheet>
          <span className="truncate text-sm font-semibold">{organization.name}</span>
        </header>

        <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}

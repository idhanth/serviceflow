import { redirect } from "next/navigation";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getSessionToken } from "@/lib/session";

import { DemoAccounts } from "./demo-accounts";
import { LoginForm } from "./login-form";

export default async function LoginPage() {
  if (await getSessionToken()) redirect("/dashboard");

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 px-4 py-12">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-2 text-center">
          <div className="mx-auto flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <span className="text-lg font-semibold">S</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Sign in to ServiceFlow</h1>
          <p className="text-sm text-muted-foreground">
            Operations for service businesses.
          </p>
        </div>

        <Card>
          <CardHeader className="sr-only">
            <CardTitle>Sign in</CardTitle>
            <CardDescription>Enter your email and password.</CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <LoginForm />
          </CardContent>
        </Card>

        <DemoAccounts />
      </div>
    </main>
  );
}

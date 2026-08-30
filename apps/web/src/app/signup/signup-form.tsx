"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch, ApiError } from "@/lib/api-client";

const schema = z.object({
  first_name: z.string().trim().min(1, "Enter your first name.").max(100),
  last_name: z.string().trim().min(1, "Enter your last name.").max(100),
  email: z.string().trim().min(1, "Enter your email address.").email("Enter a valid email address."),
  phone: z.string().trim().max(40).optional(),
  password: z.string().min(8, "Use at least 8 characters.").max(256),
});

type FormValues = z.infer<typeof schema>;

export function SignupForm({ organizationSlug }: { organizationSlug: string }) {
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { first_name: "", last_name: "", email: "", phone: "", password: "" },
  });

  async function onSubmit(values: FormValues) {
    setFormError(null);
    try {
      await apiFetch("/api/auth/signup", {
        method: "POST",
        body: JSON.stringify({
          ...values,
          phone: values.phone || null,
          organization_slug: organizationSlug,
        }),
      });
      router.replace("/dashboard");
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError) {
        const fields = (error.details?.fields ?? {}) as Record<string, string>;
        if (fields.password) setError("password", { message: String(fields.password) });
        setFormError(error.message);
      } else {
        setFormError("Something went wrong creating your account. Please try again.");
      }
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
      {formError ? (
        <p
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {formError}
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="first_name">First name</Label>
          <Input
            id="first_name"
            autoComplete="given-name"
            aria-invalid={Boolean(errors.first_name)}
            {...register("first_name")}
          />
          {errors.first_name ? (
            <p className="text-sm text-destructive">{errors.first_name.message}</p>
          ) : null}
        </div>
        <div className="space-y-2">
          <Label htmlFor="last_name">Last name</Label>
          <Input
            id="last_name"
            autoComplete="family-name"
            aria-invalid={Boolean(errors.last_name)}
            {...register("last_name")}
          />
          {errors.last_name ? (
            <p className="text-sm text-destructive">{errors.last_name.message}</p>
          ) : null}
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          aria-invalid={Boolean(errors.email)}
          {...register("email")}
        />
        {errors.email ? <p className="text-sm text-destructive">{errors.email.message}</p> : null}
      </div>

      <div className="space-y-2">
        <Label htmlFor="phone">Phone (optional)</Label>
        <Input id="phone" type="tel" autoComplete="tel" {...register("phone")} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          aria-invalid={Boolean(errors.password)}
          aria-describedby="password-help"
          {...register("password")}
        />
        {errors.password ? (
          <p className="text-sm text-destructive">{errors.password.message}</p>
        ) : (
          <p id="password-help" className="text-sm text-muted-foreground">
            At least 8 characters.
          </p>
        )}
      </div>

      <Button type="submit" className="w-full" disabled={isSubmitting}>
        {isSubmitting ? (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Creating account...
          </>
        ) : (
          "Create account"
        )}
      </Button>
    </form>
  );
}

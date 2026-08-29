export type Role = "CUSTOMER" | "EMPLOYEE" | "ADMIN";

export interface MembershipSummary {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: Role;
}

export interface SessionUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  avatar_url: string | null;
  memberships: MembershipSummary[];
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  email: string;
  phone: string | null;
  timezone: string;
  address: string | null;
  logo_url: string | null;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id?: string;
  details?: Record<string, unknown>;
}

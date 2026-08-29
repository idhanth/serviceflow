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

// ---------------------------------------------------------------- phase 2

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface Paged<T> {
  data: T[];
  meta: PageMeta;
}

export interface UserSummary {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  phone: string | null;
  avatar_url: string | null;
}

export interface Customer {
  id: string;
  user: UserSummary;
  notes: string | null;
  vehicle_count: number;
  created_at: string;
}

export interface ServiceSummary {
  id: string;
  name: string;
  duration_minutes: number;
}

export interface Employee {
  id: string;
  user: UserSummary;
  job_title: string;
  active: boolean;
  services: ServiceSummary[];
}

export interface Service {
  id: string;
  name: string;
  description: string | null;
  base_price: string;
  duration_minutes: number;
  active: boolean;
  image_url: string | null;
  employee_count: number;
}

export interface VehicleOwner {
  customer_id: string;
  full_name: string;
}

export interface Vehicle {
  id: string;
  customer_id: string;
  year: number;
  make: string;
  model: string;
  color: string | null;
  license_plate: string | null;
  notes: string | null;
  display_name: string;
  owner: VehicleOwner | null;
  created_at: string;
}

/** The six roles held inside a business. Platform administration is a user flag. */
export type Role = "OWNER" | "MANAGER" | "DISPATCHER" | "TECHNICIAN" | "CUSTOMER" | "ANALYST";

/** Mirrors apps/api/src/serviceflow/auth/permissions.py. */
export type Permission =
  | "organization:manage"
  | "members:read"
  | "members:manage"
  | "customers:read"
  | "customers:write"
  | "customers:archive"
  | "employees:read"
  | "employees:write"
  | "services:write"
  | "services:read_retired"
  | "availability:manage"
  | "availability:own"
  | "bookings:read"
  | "bookings:write"
  | "bookings:own"
  | "jobs:read"
  | "jobs:dispatch"
  | "jobs:work"
  | "schedule:read"
  | "schedule:own"
  | "audit:read"
  | "search"
  | "infrastructure:read"
  | "dashboard:read"
  | "platform:tenants";

export interface MembershipSummary {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: Role;
  permissions: Permission[];
}

export interface SessionUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  avatar_url: string | null;
  is_platform_admin: boolean;
  platform_permissions: Permission[];
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
  address: string | null;
  notes: string | null;
  archived: boolean;
  booking_count: number;
  completed_jobs: number;
  last_service_at: string | null;
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

// ---------------------------------------------------------------- phase 3

export type BookingStatus = "PENDING" | "CONFIRMED" | "REJECTED" | "CANCELLED";
export type JobStatus = "NEW" | "SCHEDULED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";

export interface BookingService {
  id: string;
  name: string;
  duration_minutes: number;
  base_price: string;
}

export interface BookingCustomer {
  id: string;
  full_name: string;
  email: string;
  phone: string | null;
  address: string | null;
}

export interface BookingJobSummary {
  id: string;
  status: JobStatus;
  scheduled_start: string;
  scheduled_end: string;
  started_at: string | null;
  completed_at: string | null;
  employee_id: string | null;
  employee_name: string | null;
}

export interface Booking {
  id: string;
  status: BookingStatus;
  requested_start: string;
  requested_end: string;
  customer_notes: string | null;
  admin_notes: string | null;
  service: BookingService;
  customer: BookingCustomer | null;
  job: BookingJobSummary | null;
  created_at: string;
}

export interface AssignableEmployee {
  id: string;
  full_name: string;
  job_title: string;
  available: boolean;
  conflict: boolean;
  assignable: boolean;
  reason: string | null;
  jobs_today: number;
  scheduled_minutes_today: number;
  conflicting_job_id: string | null;
}

export interface JobEmployee {
  id: string;
  full_name: string;
  job_title: string;
}

export interface Job {
  id: string;
  booking_id: string;
  booking_status: BookingStatus;
  status: JobStatus;
  scheduled_start: string;
  scheduled_end: string;
  started_at: string | null;
  completed_at: string | null;
  internal_notes: string | null;
  employee: JobEmployee | null;
  customer: BookingCustomer;
  service: BookingService;
  customer_notes: string | null;
  created_at: string;
}

// ---------------------------------------------------------------- phase 4

/** Weekday numbering matches the API: Monday 0 ... Sunday 6. */
export interface WeeklyWindow {
  id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
}

export interface WeeklyWindowInput {
  day_of_week: number;
  start_time: string;
  end_time: string;
}

export interface AvailabilityOverride {
  id: string;
  date: string;
  available: boolean;
  start_time: string | null;
  end_time: string | null;
  reason: string | null;
}

export interface Availability {
  employee_id: string;
  full_name: string;
  timezone: string;
  weekly: WeeklyWindow[];
  overrides: AvailabilityOverride[];
}

export interface ScheduleEntry {
  id: string;
  booking_id: string;
  booking_status: BookingStatus;
  status: JobStatus;
  scheduled_start: string;
  scheduled_end: string;
  duration_minutes: number;
  employee_id: string | null;
  employee_name: string | null;
  service_id: string;
  service_name: string;
  customer_name: string;
  customer_address: string | null;
}

export interface WorkingWindow {
  /** Local "HH:MM" in the business's timezone. */
  start: string;
  end: string;
}

export interface ScheduleDay {
  date: string;
  windows: WorkingWindow[];
  unavailable_reason: string | null;
}

export interface ScheduleLane {
  employee_id: string;
  full_name: string;
  job_title: string;
  days: ScheduleDay[];
}

export interface ScheduleFeed {
  timezone: string;
  start: string;
  end: string;
  lanes: ScheduleLane[];
  entries: ScheduleEntry[];
  can_view_team: boolean;
}

export interface DashboardCounts {
  bookings_today: number;
  jobs_in_progress: number;
  jobs_completed_today: number;
  jobs_remaining_today: number;
  technicians_working_today: number;
  technicians_total: number;
  unassigned_jobs: number;
  pending_bookings: number;
}

export interface CustomerBrief {
  id: string;
  full_name: string;
  address: string | null;
  created_at: string;
}

export interface DashboardData {
  timezone: string;
  date: string;
  counts: DashboardCounts;
  needs_attention: ScheduleEntry[];
  overdue: ScheduleEntry[];
  upcoming: ScheduleEntry[];
  recent_customers: CustomerBrief[];
}

export type MembershipStatus = "ACTIVE" | "INVITED" | "SUSPENDED";

export interface Member {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
  status: MembershipStatus;
  can_sign_in: boolean;
  created_at: string;
}

export interface TenantSummary {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  created_at: string;
  members: number;
  customers: number;
  employees: number;
  bookings: number;
  jobs: number;
}

// ---------------------------------------------------------------- phase 5

export type NoteVisibility = "INTERNAL" | "CUSTOMER_VISIBLE";
export type PhotoType = "BEFORE" | "AFTER" | "OTHER";

export interface JobNote {
  id: string;
  content: string;
  visibility: NoteVisibility;
  author_name: string;
  created_at: string;
}

export interface JobPhoto {
  id: string;
  photo_type: PhotoType;
  mime_type: string;
  file_size: number;
  uploaded_by_name: string;
  created_at: string;
  /** Short-lived presigned GET; the bucket itself is private. */
  url: string;
}

export interface PhotoPresign {
  url: string;
  fields: Record<string, string>;
  storage_key: string;
  expires_in: number;
  max_bytes: number;
}

export type NotificationType =
  | "BOOKING_CREATED"
  | "BOOKING_CONFIRMED"
  | "BOOKING_REJECTED"
  | "BOOKING_RESCHEDULED"
  | "BOOKING_CANCELLED"
  | "APPOINTMENT_REMINDER"
  | "JOB_STARTED"
  | "JOB_COMPLETED";

export interface AppNotification {
  id: string;
  type: NotificationType;
  subject: string;
  body: string;
  unread: boolean;
  payload: Record<string, string | null> | null;
  created_at: string;
}

export interface SearchResult {
  kind: "customer" | "booking" | "job" | "employee" | "service";
  id: string;
  title: string;
  subtitle: string;
  href: string;
}

export type AuditAction =
  | "BOOKING_CREATED"
  | "BOOKING_CONFIRMED"
  | "BOOKING_REJECTED"
  | "BOOKING_RESCHEDULED"
  | "BOOKING_CANCELLED"
  | "JOB_ASSIGNED"
  | "JOB_REASSIGNED"
  | "JOB_STARTED"
  | "JOB_COMPLETED"
  | "JOB_CANCELLED"
  | "NOTE_ADDED"
  | "NOTE_DELETED"
  | "PHOTO_DELETED"
  | "CUSTOMER_CREATED"
  | "CUSTOMER_UPDATED"
  | "CUSTOMER_ARCHIVED"
  | "EMPLOYEE_CREATED"
  | "EMPLOYEE_UPDATED"
  | "EMPLOYEE_DEACTIVATED"
  | "EMPLOYEE_REACTIVATED"
  | "SERVICE_CREATED"
  | "SERVICE_UPDATED"
  | "SERVICE_RETIRED"
  | "USER_INVITED"
  | "USER_ROLE_CHANGED"
  | "MEMBER_SUSPENDED"
  | "MEMBER_REACTIVATED"
  | "ORGANIZATION_UPDATED"
  | "TENANT_CREATED"
  | "AVAILABILITY_UPDATED"
  | "AVAILABILITY_OVERRIDE_SET"
  | "AVAILABILITY_OVERRIDE_REMOVED";

/** One entry in the append-only audit trail. */
export interface AuditEntry {
  id: string;
  action: AuditAction;
  actor_name: string;
  resource_type: string;
  resource_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditActor {
  id: string;
  full_name: string;
}

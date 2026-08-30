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

// ---------------------------------------------------------------- phase 3

export type BookingStatus = "PENDING" | "CONFIRMED" | "REJECTED" | "CANCELLED";
export type JobStatus = "ASSIGNED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";

export interface BookingVehicle {
  id: string;
  display_name: string;
  license_plate: string | null;
  color: string | null;
}

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
}

export interface BookingJobSummary {
  id: string;
  status: JobStatus;
  scheduled_start: string;
  scheduled_end: string;
  started_at: string | null;
  completed_at: string | null;
  employee_name: string;
}

export interface Booking {
  id: string;
  status: BookingStatus;
  requested_start: string;
  requested_end: string;
  customer_notes: string | null;
  admin_notes: string | null;
  vehicle: BookingVehicle;
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
  status: JobStatus;
  scheduled_start: string;
  scheduled_end: string;
  started_at: string | null;
  completed_at: string | null;
  internal_notes: string | null;
  employee: JobEmployee;
  customer: BookingCustomer;
  vehicle: BookingVehicle;
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

export interface CalendarEvent {
  id: string;
  booking_id: string;
  status: JobStatus;
  scheduled_start: string;
  scheduled_end: string;
  duration_minutes: number;
  employee_id: string;
  employee_name: string;
  service_id: string;
  service_name: string;
  customer_name: string;
  vehicle_name: string;
}

export interface CalendarFeed {
  timezone: string;
  start: string;
  end: string;
  data: CalendarEvent[];
  can_filter_by_employee: boolean;
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
  kind: "customer" | "vehicle" | "booking" | "job" | "employee" | "service";
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
  | "EMPLOYEE_CREATED"
  | "EMPLOYEE_UPDATED"
  | "EMPLOYEE_DEACTIVATED"
  | "EMPLOYEE_REACTIVATED"
  | "SERVICE_CREATED"
  | "SERVICE_UPDATED"
  | "SERVICE_RETIRED"
  | "VEHICLE_ARCHIVED"
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

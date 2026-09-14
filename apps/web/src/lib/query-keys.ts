/** Centralized query keys so mutations can invalidate precisely. */

export const queryKeys = {
  customers: {
    all: ["customers"] as const,
    list: (params: Record<string, unknown>) => ["customers", "list", params] as const,
    detail: (id: string) => ["customers", "detail", id] as const,
    me: ["customers", "me"] as const,
  },
  employees: {
    all: ["employees"] as const,
    list: (params: Record<string, unknown>) => ["employees", "list", params] as const,
    detail: (id: string) => ["employees", "detail", id] as const,
  },
  services: {
    all: ["services"] as const,
    list: (params: Record<string, unknown>) => ["services", "list", params] as const,
  },
  bookings: {
    all: ["bookings"] as const,
    list: (params: Record<string, unknown>) => ["bookings", "list", params] as const,
    detail: (id: string) => ["bookings", "detail", id] as const,
    assignable: (id: string) => ["bookings", "assignable", id] as const,
    candidates: (params: Record<string, unknown>) => ["bookings", "candidates", params] as const,
  },
  availability: {
    all: ["availability"] as const,
    detail: (employeeId: string) => ["availability", employeeId] as const,
  },
  schedule: {
    all: ["schedule"] as const,
    range: (params: Record<string, unknown>) => ["schedule", "range", params] as const,
  },
  dashboard: {
    all: ["dashboard"] as const,
  },
  jobs: {
    all: ["jobs"] as const,
    list: (params: Record<string, unknown>) => ["jobs", "list", params] as const,
    detail: (id: string) => ["jobs", "detail", id] as const,
    notes: (id: string) => ["jobs", "notes", id] as const,
    photos: (id: string) => ["jobs", "photos", id] as const,
  },
  members: {
    all: ["members"] as const,
    list: (params: Record<string, unknown>) => ["members", "list", params] as const,
  },
  organization: {
    current: ["organization", "current"] as const,
  },
  platform: {
    tenants: ["platform", "tenants"] as const,
  },
  notifications: {
    all: ["notifications"] as const,
    list: (params: Record<string, unknown>) => ["notifications", "list", params] as const,
    unread: ["notifications", "unread"] as const,
  },
  activity: {
    all: ["activity"] as const,
    list: (params: Record<string, unknown>) => ["activity", "list", params] as const,
    actors: ["activity", "actors"] as const,
  },
  search: {
    all: ["search"] as const,
    query: (term: string) => ["search", term] as const,
  },
} as const;

/** Everything a booking or job change can make stale, in one place. */
export const OPERATIONS_KEYS = [
  queryKeys.bookings.all,
  queryKeys.jobs.all,
  queryKeys.schedule.all,
  queryKeys.dashboard.all,
  queryKeys.customers.all,
] as const;

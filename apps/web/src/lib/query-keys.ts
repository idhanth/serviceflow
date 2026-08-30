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
  vehicles: {
    all: ["vehicles"] as const,
    list: (params: Record<string, unknown>) => ["vehicles", "list", params] as const,
  },
  bookings: {
    all: ["bookings"] as const,
    list: (params: Record<string, unknown>) => ["bookings", "list", params] as const,
    detail: (id: string) => ["bookings", "detail", id] as const,
    assignable: (id: string) => ["bookings", "assignable", id] as const,
  },
  availability: {
    all: ["availability"] as const,
    detail: (employeeId: string) => ["availability", employeeId] as const,
  },
  calendar: {
    all: ["calendar"] as const,
    range: (params: Record<string, unknown>) => ["calendar", "range", params] as const,
  },
  jobs: {
    all: ["jobs"] as const,
    list: (params: Record<string, unknown>) => ["jobs", "list", params] as const,
    detail: (id: string) => ["jobs", "detail", id] as const,
  },
} as const;

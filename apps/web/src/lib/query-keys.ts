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
} as const;

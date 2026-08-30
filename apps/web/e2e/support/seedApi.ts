import { expect } from "@playwright/test";

import { apiFor, jsonOf } from "./helpers";
import type { Booking, Employee, Job, Service, Vehicle } from "./types";

/**
 * Preconditions created through the API rather than the UI.
 *
 * Used only for state a spec needs but is not testing - a spec about the admin
 * queue should not re-drive the customer wizard first. Every call goes through
 * the app's own proxy with a real browser session, so these use exactly the
 * access the signed-in role has, and nothing here can see more than the UI can.
 */
const SHOP_TIMEZONE = process.env.E2E_SHOP_TIMEZONE ?? "America/Los_Angeles";
/** Tue/Wed/Thu: everyone works those days, and nobody works Sunday. */
const SAFE_WEEKDAYS = new Set(["Tue", "Wed", "Thu"]);
/** The demo technician the employee-facing specs drive. */
export const DEMO_TECHNICIAN = "Maria Santos";

function partsInShopZone(instant: Date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: SHOP_TIMEZONE,
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(instant);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return { weekday: get("weekday"), year: get("year"), month: get("month"), day: get("day") };
}

/** How far the shop's zone is from UTC at this instant, in minutes. */
function shopOffsetMinutes(instant: Date): number {
  const utc = new Date(instant.toLocaleString("en-US", { timeZone: "UTC" }));
  const shop = new Date(instant.toLocaleString("en-US", { timeZone: SHOP_TIMEZONE }));
  return Math.round((shop.getTime() - utc.getTime()) / 60_000);
}

/**
 * The instant at which it is `shopHour`:00 in the shop's timezone, on the first
 * day at least `daysAhead` out that the whole team works.
 *
 * The shop's zone, not the machine's and not UTC: availability is local
 * wall-clock. A slot picked as "15:00 UTC" lands at 8am shop time, before most
 * of the team starts, so every candidate comes back unavailable and the test
 * proves nothing.
 */
export function workingSlot(daysAhead: number, shopHour = 11): string {
  const cursor = new Date(Date.now() + daysAhead * 86_400_000);
  for (let attempt = 0; attempt < 7; attempt += 1) {
    const { weekday, year, month, day } = partsInShopZone(cursor);
    if (SAFE_WEEKDAYS.has(weekday)) {
      const naive = Date.UTC(Number(year), Number(month) - 1, Number(day), shopHour, 0, 0, 0);
      return new Date(naive - shopOffsetMinutes(new Date(naive)) * 60_000).toISOString();
    }
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  throw new Error("no workable weekday found within a week");
}

export async function ensureVehicleViaApi(plate: string): Promise<string> {
  const api = await apiFor("customer");
  const existing = await jsonOf<Vehicle[]>(
    await api.get("/api/proxy/vehicles?page_size=100"),
    "listing vehicles",
  );
  const found = existing.data.find((vehicle) => vehicle.license_plate === plate);
  if (found) return found.id;

  const created = await jsonOf<Vehicle>(
    await api.post("/api/proxy/vehicles", {
      data: { year: 2021, make: "Subaru", model: "Outback", color: "Slate", license_plate: plate },
    }),
    "creating a vehicle",
  );
  return created.data.id;
}

export async function serviceNamed(name: string): Promise<Service> {
  const api = await apiFor("customer");
  const body = await jsonOf<Service[]>(
    await api.get("/api/proxy/services?page_size=50"),
    "listing services",
  );
  const service = body.data.find((item) => item.name === name);
  expect(service, `no service called ${name}`).toBeTruthy();
  return service!;
}

/** Creates a pending booking for this run's customer at an explicit instant. */
export async function pendingBookingAt({
  plate,
  serviceName = "Express Wash",
  iso,
}: {
  plate: string;
  serviceName?: string;
  iso: string;
}): Promise<Booking> {
  const api = await apiFor("customer");
  const vehicleId = await ensureVehicleViaApi(plate);
  const service = await serviceNamed(serviceName);

  const created = await jsonOf<Booking>(
    await api.post("/api/proxy/bookings", {
      data: { vehicle_id: vehicleId, service_id: service.id, requested_start: iso },
    }),
    "creating a booking",
  );
  return created.data;
}

/** Every job a technician already holds, paged (the API caps page_size at 100). */
async function jobsOf(employeeId: string): Promise<{ start: number; end: number }[]> {
  const api = await apiFor("admin");
  const taken: { start: number; end: number }[] = [];
  for (let page = 1; page <= 10; page += 1) {
    const body = await jsonOf<Job[]>(
      await api.get(`/api/proxy/jobs?employee_id=${employeeId}&page=${page}&page_size=100`),
      "listing jobs",
    );
    for (const job of body.data) {
      taken.push({ start: Date.parse(job.scheduled_start), end: Date.parse(job.scheduled_end) });
    }
    if (page >= body.meta.pages) break;
  }
  return taken;
}

/**
 * A slot in which the demo technician is genuinely free.
 *
 * Fixed slots made the suite fail the second time it ran against the same
 * database: the technician was already booked then by the previous run, which
 * the product correctly refuses. This walks candidate days and hours, skipping
 * anything that overlaps work she already has, so a run is not hostage to
 * earlier ones.
 */
export async function freeSlotForTechnician({
  fromDaysAhead = 30,
  technician = DEMO_TECHNICIAN,
  durationMinutes = 45,
} = {}): Promise<{ iso: string; employeeId: string }> {
  const api = await apiFor("admin");
  const employees = await jsonOf<Employee[]>(
    await api.get("/api/proxy/employees?page_size=50"),
    "listing employees",
  );
  const employee = employees.data.find((candidate) => candidate.user.full_name === technician);
  expect(employee, `no employee called ${technician}`).toBeTruthy();

  const taken = await jobsOf(employee!.id);
  for (let day = fromDaysAhead; day < fromDaysAhead + 21; day += 1) {
    for (const shopHour of [9, 10, 11, 12, 13, 14, 15]) {
      const iso = workingSlot(day, shopHour);
      const start = Date.parse(iso);
      const end = start + durationMinutes * 60_000;
      if (!taken.some((job) => start < job.end && end > job.start)) {
        return { iso, employeeId: employee!.id };
      }
    }
  }
  throw new Error(`no free slot for ${technician} in the next three weeks`);
}

/**
 * A future job that already exists, so a spec can deliberately collide with it.
 *
 * Reading a real assignment beats inventing a time and hoping somebody is on
 * it: whoever holds this job is, by definition, busy then. Far enough out that a
 * booking placed on top lands on the first page of the pending queue, which is
 * sorted latest-first.
 */
export async function anExistingFutureJob(): Promise<{ start: string; employeeName: string }> {
  const api = await apiFor("admin");
  const cutoff = Date.now() + 25 * 86_400_000;

  for (let page = 1; page <= 10; page += 1) {
    const body = await jsonOf<Job[]>(
      await api.get(`/api/proxy/jobs?status=ASSIGNED&page=${page}&page_size=100`),
      "listing jobs",
    );
    const upcoming = body.data.find((job) => Date.parse(job.scheduled_start) > cutoff);
    if (upcoming) {
      return { start: upcoming.scheduled_start, employeeName: upcoming.employee.full_name };
    }
    if (page >= body.meta.pages) break;
  }
  throw new Error("no future assigned job to collide with");
}

/**
 * A confirmed job for this run's customer, assigned to the demo technician.
 *
 * Specs that need "a job to work on" build one rather than borrowing whatever
 * an earlier spec left behind, so each file can be run on its own.
 */
export async function confirmedJobForRunCustomer({
  plate,
  fromDaysAhead = 34,
}: {
  plate: string;
  fromDaysAhead?: number;
}): Promise<{ jobId: string; bookingId: string }> {
  const { iso, employeeId } = await freeSlotForTechnician({ fromDaysAhead });
  const booking = await pendingBookingAt({ plate, iso });
  const admin = await apiFor("admin");

  const confirmed = await jsonOf<Booking>(
    await admin.post(`/api/proxy/bookings/${booking.id}/confirm`, {
      data: { employee_id: employeeId },
    }),
    "confirming a booking",
  );
  return { jobId: confirmed.data.job!.id, bookingId: booking.id };
}



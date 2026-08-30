/**
 * The parts of the API's payloads these tests actually read.
 *
 * Deliberately partial: a test should depend on the fields it asserts about and
 * nothing else, so an unrelated schema change does not ripple through the suite.
 */
export interface Vehicle {
  id: string;
  license_plate: string;
  display_name?: string;
}

export interface Service {
  id: string;
  name: string;
  duration_minutes: number;
}

export interface Employee {
  id: string;
  user: { full_name: string };
}

export interface Job {
  id: string;
  status: string;
  scheduled_start: string;
  scheduled_end: string;
  employee: { full_name: string };
}

export interface Booking {
  id: string;
  status: string;
  service: Service;
  vehicle: Vehicle;
  requested_start: string;
  job: Job | null;
}

export interface Photo {
  id: string;
  file_size: number;
  mime_type: string;
}

export interface Note {
  id: string;
  content: string;
  visibility: string;
}

export interface ActivityEntry {
  action: string;
  actor_name: string;
  resource_type: string;
}

export interface AppNotification {
  id: string;
  subject: string;
}

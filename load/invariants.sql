-- What has to still be true after a load run.
-- Every row returned by this file is a violation; a clean run prints zeros.

\echo '== duplicate bookings under one idempotency key (must be 0) =='
select count(*) as violations
from (
  select organization_id, user_id, key, count(*) as uses
  from idempotency_records
  group by 1, 2, 3
  having count(*) > 1
) duplicated;

\echo '== confirmed bookings without exactly one job (must be 0) =='
select count(*) as violations
from bookings b
left join jobs j on j.booking_id = b.id
where b.status = 'CONFIRMED'
group by b.id
having count(j.id) <> 1;

\echo '== overlapping jobs for one employee (must be 0) =='
select count(*) as violations
from jobs a
join jobs b
  on a.employee_id = b.employee_id
 and a.id <> b.id
 and a.scheduled_start < b.scheduled_end
 and a.scheduled_end > b.scheduled_start
where a.status <> 'CANCELLED' and b.status <> 'CANCELLED';

\echo '== bookings whose vehicle or service belongs to another organization (must be 0) =='
select count(*) as violations
from bookings b
join vehicles v on v.id = b.vehicle_id
join services s on s.id = b.service_id
where v.organization_id <> b.organization_id or s.organization_id <> b.organization_id;

\echo '== jobs whose employee belongs to another organization (must be 0) =='
select count(*) as violations
from jobs j
join employees e on e.id = j.employee_id
where e.organization_id <> j.organization_id;

\echo '== bookings that end before they start, or with no end (must be 0) =='
select count(*) as violations from bookings where requested_end <= requested_start;

\echo '== idempotency records pointing at a booking that does not exist (must be 0) =='
select count(*) as violations
from idempotency_records r
where r.resource_type = 'booking'
  and r.resource_id is not null
  and not exists (select 1 from bookings b where b.id = r.resource_id);

\echo '== audit rows with no actor (must be 0) =='
select count(*) as violations from audit_logs where actor_user_id is null;

\echo '== totals for context =='
select
  (select count(*) from bookings) as bookings,
  (select count(*) from jobs) as jobs,
  (select count(*) from idempotency_records) as idempotency_records,
  (select count(*) from audit_logs) as audit_entries;

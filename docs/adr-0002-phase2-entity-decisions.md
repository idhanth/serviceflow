# ADR 0002 - Entity decisions in phase 2

Status: accepted
Date: 2026-08-29

Four choices in the customers/employees/services/vehicles work that the PRD
leaves open, recorded because later phases depend on them.

## 1. Identity is global, membership is per-organization

`find_or_create_user` resolves a `User` by email across the whole system and
attaches a per-organization `Customer` or `Employee` record to it. One person can
therefore be a customer of several shops with one identity, which matches the
multi-tenant model in PRD 5-6.

The trade-off: when an admin adds someone who already exists, the returned record
carries that person's existing name rather than the typed one, which reveals that
the email is already a ServiceFlow user. This is the same behaviour Slack and
Stripe have, the disclosure is limited to "this address is known", and the
alternative - per-organization duplicate user rows - breaks the single-identity
model the PRD asks for. Accepted deliberately.

## 2. Staff-created accounts cannot sign in

A `User` created by an admin has `password_hash = NULL`, so `verify_password`
always fails. Customers and employees added through the UI exist as records but
have no credentials until a sign-up or invitation flow exists. `MembershipStatus.
INVITED` is deliberately left unused rather than misapplied here: an invited
membership would also block access *after* credentials were set, which would need
an activation step that does not exist yet.

## 3. Services soft-delete, vehicles hard-delete

`DELETE /services/{id}` sets `active = false` and returns the record. Bookings and
jobs will reference services from phase 3, and removing the row would destroy job
history; retired services stay readable to admins and invisible to everyone else.

Vehicles are genuinely deleted, which is correct while nothing references them.
**Phase 3 must revisit this**: once a booking points at a vehicle, deleting it
either needs a guard or the same soft-delete treatment.

## 4. Deactivation is an access change, not a flag

Setting `Employee.active = false` also moves their `OrganizationMembership` to
`SUSPENDED`, so `get_current_user` refuses them on the next request. PRD 53 lists
"employee becomes inactive" as a failure case to handle, and hiding someone from
a list while leaving their token working would not satisfy it. Reactivating
restores the membership. Both directions are tested.

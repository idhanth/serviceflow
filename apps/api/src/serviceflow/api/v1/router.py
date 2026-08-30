from __future__ import annotations

from fastapi import APIRouter

from serviceflow.api.v1 import (
    auth,
    availability,
    bookings,
    calendar,
    customers,
    employees,
    jobs,
    organizations,
    services,
    vehicles,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(customers.router)
api_router.include_router(employees.router)
api_router.include_router(availability.router)
api_router.include_router(services.router)
api_router.include_router(vehicles.router)
api_router.include_router(bookings.router)
api_router.include_router(jobs.router)
api_router.include_router(calendar.router)

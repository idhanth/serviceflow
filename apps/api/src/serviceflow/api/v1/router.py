from __future__ import annotations

from fastapi import APIRouter

from serviceflow.api.v1 import (
    activity,
    auth,
    availability,
    bookings,
    customers,
    dashboard,
    employees,
    events,
    job_content,
    jobs,
    members,
    notifications,
    organizations,
    platform,
    schedule,
    scheduling,
    search,
    services,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(auth.me_router)
api_router.include_router(organizations.router)
api_router.include_router(members.router)
api_router.include_router(platform.router)
api_router.include_router(dashboard.router)
api_router.include_router(customers.router)
api_router.include_router(employees.router)
api_router.include_router(availability.router)
api_router.include_router(services.router)
api_router.include_router(bookings.router)
api_router.include_router(jobs.router)
api_router.include_router(job_content.router)
api_router.include_router(schedule.router)
api_router.include_router(scheduling.router)
api_router.include_router(notifications.router)
api_router.include_router(search.router)
api_router.include_router(activity.router)
api_router.include_router(events.router)

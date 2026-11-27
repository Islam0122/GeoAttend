from fastapi import APIRouter

from app.api.v1.endpoints import (
    automatic,
    monitoring,
    attendance,
    auth,
    employees,
    locations,
    offices,
    organization,
    reports,
    schedules,
)

api_router = APIRouter(prefix="/api/v1")
for r in (automatic.router, monitoring.router, auth.router, organization.router, employees.router, offices.router, schedules.router, locations.router, attendance.router, reports.router):
    api_router.include_router(r)
api_router.include_router(reports.me_router)

# API endpoints

Generated from the live OpenAPI schema (`docs/openapi.json`). Interactive docs: `/api/docs`.

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/v1/anomalies/` | List Anomalies |
| `POST` | `/api/v1/anomalies/{anomaly_id}/review/` | Review Anomaly |
| `GET` | `/api/v1/attendance/` | List Records |
| `GET` | `/api/v1/attendance/approvals/` | Pending Approvals |
| `GET` | `/api/v1/attendance/automatic/status/` | Automatic Status View |
| `GET` | `/api/v1/attendance/automatic/today/` | Automatic Today |
| `POST` | `/api/v1/attendance/break/end/` | Break End |
| `POST` | `/api/v1/attendance/break/start/` | Break Start |
| `POST` | `/api/v1/attendance/check-in/` | Check In |
| `POST` | `/api/v1/attendance/check-out/` | Check Out |
| `GET` | `/api/v1/attendance/corrections/` | List Corrections |
| `POST` | `/api/v1/attendance/corrections/{correction_id}/review/` | Review Correction |
| `GET` | `/api/v1/attendance/dashboard/` | Dashboard |
| `POST` | `/api/v1/attendance/manual-check-in/` | Check In |
| `POST` | `/api/v1/attendance/manual-check-out/` | Check Out |
| `POST` | `/api/v1/attendance/manual-record/` | Manual Record |
| `GET` | `/api/v1/attendance/policy/` | Get Policy |
| `PATCH` | `/api/v1/attendance/policy/` | Patch Policy |
| `POST` | `/api/v1/attendance/presence-check/` | Presence Check |
| `GET` | `/api/v1/attendance/sessions/` | List Sessions |
| `PATCH` | `/api/v1/attendance/sessions/{session_id}/` | Override Session |
| `GET` | `/api/v1/attendance/today/` | Today |
| `GET` | `/api/v1/attendance/today/team/` | Team Today |
| `GET` | `/api/v1/attendance/{record_id}/` | Get Record |
| `POST` | `/api/v1/attendance/{record_id}/approve/` | Approve Record |
| `POST` | `/api/v1/attendance/{record_id}/confirm/` | Confirm |
| `POST` | `/api/v1/attendance/{record_id}/correction/` | Request Correction |
| `POST` | `/api/v1/attendance/{record_id}/dispute/` | Dispute |
| `GET` | `/api/v1/audit-logs/` | Audit Logs |
| `POST` | `/api/v1/auth/accept-invite/` | Accept Invite |
| `POST` | `/api/v1/auth/change-password/` | Change Password |
| `POST` | `/api/v1/auth/google/` | Google |
| `POST` | `/api/v1/auth/login/` | Login |
| `POST` | `/api/v1/auth/logout/` | Logout |
| `GET` | `/api/v1/auth/me/` | Me |
| `POST` | `/api/v1/auth/refresh/` | Refresh |
| `POST` | `/api/v1/auth/register/` | Register |
| `POST` | `/api/v1/consent/` | Set Consent |
| `GET` | `/api/v1/consent/me/` | My Consent |
| `GET` | `/api/v1/departments/` | List Departments |
| `POST` | `/api/v1/departments/` | Create Department |
| `PATCH` | `/api/v1/departments/{dept_id}/` | Rename Department |
| `DELETE` | `/api/v1/departments/{dept_id}/` | Delete Department |
| `POST` | `/api/v1/devices/heartbeat/` | Heartbeat |
| `GET` | `/api/v1/devices/me/` | My Devices |
| `POST` | `/api/v1/devices/register/` | Register Device |
| `DELETE` | `/api/v1/devices/{device_pk}/` | Deactivate Device |
| `GET` | `/api/v1/employees/` | List Employees |
| `POST` | `/api/v1/employees/` | Create Employee |
| `GET` | `/api/v1/employees/{employee_id}/` | Get Employee |
| `PATCH` | `/api/v1/employees/{employee_id}/` | Patch Employee |
| `DELETE` | `/api/v1/employees/{employee_id}/` | Delete Employee |
| `POST` | `/api/v1/employees/{employee_id}/resend-invite/` | Resend Invite |
| `GET` | `/api/v1/leave-requests/` | List Leave |
| `POST` | `/api/v1/leave-requests/` | Create Absence |
| `POST` | `/api/v1/leave-requests/{absence_id}/cancel/` | Cancel Leave |
| `POST` | `/api/v1/leave-requests/{absence_id}/review/` | Review Absence |
| `POST` | `/api/v1/locations/batch/` | Post Batch |
| `POST` | `/api/v1/locations/events/` | Post Event |
| `GET` | `/api/v1/locations/me/history/` | My History |
| `GET` | `/api/v1/locations/me/status/` | My Status |
| `GET` | `/api/v1/locations/monitoring/` | Monitoring |
| `GET` | `/api/v1/locations/uncertain/` | Uncertain Events |
| `GET` | `/api/v1/monitoring/employees/` | Employees |
| `GET` | `/api/v1/monitoring/summary/` | Summary |
| `GET` | `/api/v1/notifications/` | My Notifications |
| `POST` | `/api/v1/notifications/{notification_id}/read/` | Mark Read |
| `GET` | `/api/v1/offices/` | List Offices |
| `POST` | `/api/v1/offices/` | Create Office |
| `GET` | `/api/v1/offices/{office_id}/` | Get Office |
| `PATCH` | `/api/v1/offices/{office_id}/` | Patch Office |
| `DELETE` | `/api/v1/offices/{office_id}/` | Delete Office |
| `GET` | `/api/v1/offices/{office_id}/geofence/` | Get Geofence |
| `PATCH` | `/api/v1/offices/{office_id}/geofence/` | Patch Geofence |
| `GET` | `/api/v1/organizations/current/` | Get Org |
| `PATCH` | `/api/v1/organizations/current/` | Patch Org |
| `GET` | `/api/v1/organizations/current/billing/` | Billing |
| `PATCH` | `/api/v1/organizations/current/billing/` | Change Plan |
| `GET` | `/api/v1/organizations/current/settings/` | Get Settings  |
| `PATCH` | `/api/v1/organizations/current/settings/` | Patch Settings |
| `GET` | `/api/v1/plans/` | List Plans |
| `GET` | `/api/v1/reports/absences/` | Absences |
| `GET` | `/api/v1/reports/daily/` | Daily |
| `GET` | `/api/v1/reports/departments/` | Departments |
| `GET` | `/api/v1/reports/early-leaves/` | Early Leaves |
| `GET` | `/api/v1/reports/export/` | Export |
| `GET` | `/api/v1/reports/late-arrivals/` | Late Arrivals |
| `GET` | `/api/v1/reports/me/` | My Report |
| `GET` | `/api/v1/reports/monthly/` | Monthly |
| `GET` | `/api/v1/reports/overtime/` | Overtime |
| `GET` | `/api/v1/reports/snapshots/` | Snapshots |
| `GET` | `/api/v1/reports/trends/` | Trends |
| `GET` | `/api/v1/reports/weekly/` | Weekly |
| `GET` | `/api/v1/schedules/` | List Schedules |
| `POST` | `/api/v1/schedules/` | Create Schedule |
| `POST` | `/api/v1/schedules/assign/` | Create Assignment |
| `GET` | `/api/v1/schedules/assignments/` | List Assignments |
| `DELETE` | `/api/v1/schedules/assignments/{assignment_id}/` | Delete Assignment |
| `GET` | `/api/v1/schedules/me/` | My Schedule |
| `GET` | `/api/v1/schedules/{schedule_id}/` | Get Schedule |
| `PATCH` | `/api/v1/schedules/{schedule_id}/` | Patch Schedule |
| `GET` | `/healthz` | Healthz |

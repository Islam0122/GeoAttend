# GeoAttend — GPS Geofencing Workforce Attendance (multi-tenant SaaS, Web/PWA)

Employees open the web app, press **Check in**, and the browser's Geolocation API sends a GPS fix.
**The FastAPI backend is the final authority**: it re-validates the fix, computes distance to the office
(Haversine; cross-checked against PostGIS in the test suite), applies a conservative accuracy rule, and
only then records attendance. Late minutes, breaks, early leave, overtime, absences and reports are all
computed server-side in each office's timezone.

> No React Native, no Google Maps, no paid GPS APIs. Maps use OpenStreetMap tiles via Leaflet.
> This is a web app: it does **not** track employees in the background (see [Limitations](#limitations)).

![Employee check-in](docs/screenshots/06-mobile-checked-in.png)

---

## 1. Architecture

```
            Browser / installed PWA (React + TS)
   Geolocation API ─ IndexedDB offline queue ─ Service worker
                          │  HTTPS
                ┌─────────▼──────────┐
                │ Nginx (web image)  │  static PWA, /api reverse proxy, security headers, req limit
                └─────────┬──────────┘
                ┌─────────▼──────────┐       ┌──────────────┐
                │ FastAPI (uvicorn)  │──────▶│ PostgreSQL 16 │  + PostGIS 3.4
                │  api/v1 endpoints  │       └──────────────┘
                │  services (domain) │       ┌──────────────┐
                │  repositories      │──────▶│ Redis         │  Celery broker + rate limiter
                └────────────────────┘       └──────┬───────┘
                          ▲                         │
                ┌─────────┴──────────┐   ┌──────────▼─────────┐
                │ Celery beat        │──▶│ Celery worker      │  reminders, finalization, reports…
                └────────────────────┘   └────────────────────┘
```

### Backend layout (`backend/app`)

| Package | Responsibility |
|---|---|
| `api/v1/endpoints/` | HTTP layer only (auth, organization, employees, offices, schedules + leave, locations + devices + consent, attendance, reports) |
| `api/deps.py` | Authentication (JWT), per-request organization membership re-validation |
| `permissions/rbac.py` | Roles, capability matrix, tenant + department scoping (`scope_employees`, `can_review_employee`) |
| `repositories/tenant.py` | Tenant-scoped data access (foreign ids behave as 404) |
| `services/` | Business logic: `geo` (Haversine, zone rule, hysteresis), `location_service` (GPS ingestion pipeline), `checkin_service` (explicit check-in/out), `attendance_service` (sessions/breaks/approvals/corrections/finalization), `calculation` (pure metrics), `schedule_service` (timezone + overnight shifts), `reports`, `automation` (jobs), `plans`, `notifications`, `audit`, `anomalies` |
| `integrations/google_oauth.py` | Google ID-token verification against Google JWKS |
| `middleware/request_context.py` | Request id, JSON access log, security headers |
| `tasks/` | Celery app, beat schedule, job wrappers |
| `models/` | SQLAlchemy 2.0 models (all business tables carry `organization_id`) |
| `core/` | Settings, DB/session, security (JWT/bcrypt), rate limiter, logging, time utilities |

**Sync vs async SQLAlchemy:** the service layer uses SQLAlchemy 2.0 in synchronous mode. It is shared
verbatim by FastAPI (threadpool endpoints) and Celery workers, and relies on row locks
(`SELECT … FOR UPDATE OF employees`) for per-employee serialization. This was a deliberate choice over
async for one consistent transactional code path.

### Frontend layout (`frontend/src`)

React 19 + TypeScript + Vite · Tailwind CSS v4 · shadcn/ui-style components on Radix primitives ·
TanStack Query (server state) · React Hook Form + Zod (forms) · Zustand (auth/UI/offline-queue state) ·
Recharts (charts) · Leaflet + OpenStreetMap (maps).

| Path | Content |
|---|---|
| `api/` | Typed client (in-memory access token, httpOnly refresh cookie with single-flight rotation), query hooks, types |
| `features/checkin/` | GPS check-in state machine (`useLocationCheck`) + `CheckInPanel` |
| `lib/geo.ts`, `lib/offlineQueue.ts` | Geolocation wrapper and IndexedDB offline queue |
| `pages/public` | Landing, Pricing, Login, Register, Google callback, Accept invite |
| `pages/employee` | My dashboard (check-in), My attendance, My schedule, My reports, Profile and location status |
| `pages/staff` | Dashboard (KPIs and charts), Attendance, Monitoring, Approvals, Corrections, Anomalies, Reports (shared by Manager and Admin portals, scoped by the API) |
| `pages/admin` | Employees, Departments, Offices and geofences, Schedules, Settings, Billing, Audit log |
| `public/sw.js`, `public/manifest.webmanifest` | PWA |

Portals by role: **Employee** (`/app/*`), **Manager** (`/app/team/*`), **Organization** for
Owner/Admin/HR/Accountant (`/app/admin/*`). A manager who is also an employee sees both portals.

---

## 2. Database schema & migrations

Alembic migrations: `backend/alembic/versions/0001_initial…` and `0002_web_pwa`. The second keeps data
(renames `absence_periods` to `leave_requests`, uses server defaults) and enables the `postgis` extension
when it is available. Both migrations upgrade, downgrade and re-upgrade cleanly, and `alembic check`
reports no model drift, on PostgreSQL 16 + PostGIS and on SQLite.

| Table | Purpose / key constraints |
|---|---|
| `organizations` | Tenant: name, unique slug, timezone, `subscription_plan`, `company_type`, `is_active` |
| `organization_settings` | All tunables: confirmation policy (AUTOMATIC / EMPLOYEE_CONFIRMATION / MANAGER_APPROVAL), GPS thresholds, check-in window, retention, reminders… (CHECK constraints) |
| `users` | Login identity, role (OWNER, ADMIN, HR, MANAGER, EMPLOYEE, ACCOUNTANT), `token_version`, invite token hash, `google_sub` (unique) |
| `refresh_tokens` | Rotation registry: unique `jti`, `family`, revoked/replaced, used for reuse detection |
| `employees` | `employee_code` unique per org, department, `position`, `employment_status`, `hired_at`, primary office |
| `departments`, `manager_departments` | Department scoping for managers |
| `offices`, `office_geofences` | lat/lng (range CHECKs), timezone; `radius_m` 10–5000, `max_accuracy_m`, hysteresis settings |
| `office_assignments` | Employee ↔ office (unique pair) |
| `work_schedules`, `schedule_days`, `schedule_assignments` | Weekly shifts (overnight supported), grace periods; assignment to exactly one of employee/department (CHECK) |
| `leave_requests` | LEAVE / SICK / BUSINESS_TRIP with PENDING / APPROVED / REJECTED |
| `location_events` | Every GPS fix: `event_type` (PRESENCE / CHECK_IN / CHECK_OUT), client `recorded_at` + server `received_at`, `client_event_id` (= event_uuid, **unique per employee → idempotency**), server-computed office, `distance_m`, `zone`, `processing_status`, `status_reason` |
| `geofence_states`, `geofence_transitions` | Presence state machine per employee and office |
| `attendance_records` | One per employee per work date (**unique**): scheduled start/end, check-in/out, late, early leave, worked, breaks, overtime, status, `is_confirmed`, `is_finalized` |
| `attendance_sessions` | Multiple per day: `check_in_event_id`, `check_out_event_id`, `check_in_at`, `check_out_at`, `duration_minutes`, confirmation, approver. **Partial unique index: at most one OPEN/AWAY session per employee** (DB-level race protection) |
| `attendance_breaks` | Lunch, temporary exit, business trip (expiry handled by jobs) |
| `attendance_corrections`, `attendance_anomalies` | Disputes/corrections with review; review signals (never auto-penalties) |
| `device_registrations`, `location_consents` | Browser/device registry with permission status; append-only consent history |
| `notifications`, `audit_logs`, `report_snapshots` | Transactional outbox, audit trail, scheduled report snapshots |

Mapping to the requested field names: `Office.radius` and `max_accuracy` are exposed directly by the API
(stored on the geofence); `LocationEvent.event_uuid` is `client_event_id`, `distance_from_office` is
`distance_m`, `validation_status` is `processing_status` + `status_reason`; `AttendanceRecord.check_in` and
`check_out` are `actual_check_in` and `actual_check_out`, and `early_leave_minutes` is `early_departure_minutes`;
`AttendanceSession.started_at` and `ended_at` are `check_in_at` and `check_out_at`.

---

## 3. REST API (`/api/v1`)

All 102 operations are listed in **[docs/endpoints.md](docs/endpoints.md)**. The full schema is in
`docs/openapi.json`, and Swagger UI is at `/api/docs`. Highlights:

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register/` · `/auth/login/` · `/auth/google/` · `/auth/refresh/` (rotation) · `/auth/logout/` · `GET /auth/me/` · `/auth/accept-invite/` · `/auth/change-password/` |
| Organization | `GET/PATCH /organizations/current/` · `…/settings/` · `…/billing/` · `GET /plans/` (public) · `/departments/` CRUD · `/audit-logs/` |
| Employees | `GET/POST /employees/` · `GET/PATCH/DELETE /employees/{id}/` · `…/resend-invite/` |
| Offices | `GET/POST /offices/` · `GET/PATCH/DELETE /offices/{id}/` · `GET/PATCH /offices/{id}/geofence/` |
| Schedules | `GET/POST /schedules/` · `PATCH /schedules/{id}/` · `POST /schedules/assign/` · `GET /schedules/me/` · `/leave-requests/` (+ review, cancel) |
| GPS | `POST /locations/events/` · `POST /locations/batch/` · `GET /locations/me/status/` · `GET /locations/me/history/` · `GET /locations/monitoring/` · `/devices/*` · `/consent/*` |
| Attendance | `POST /attendance/check-in/` · `POST /attendance/check-out/` · `/attendance/break/start|end/` · `GET /attendance/today/` · `GET /attendance/` · `GET /attendance/{id}/` · `POST /attendance/{id}/correction/` · `POST /attendance/{id}/dispute/` · `POST /attendance/{id}/approve/` · `GET /attendance/approvals/` · `GET /attendance/dashboard/` |
| Reports | `/reports/daily/` · `weekly/` · `monthly/` · `late-arrivals/` · `early-leaves/` · `absences/` · `overtime/` · `trends/` · `departments/` · `export/` (CSV) · `/reports/me/` |

Conventions: pagination is `?page=&page_size=` (≤500); filters are query params; `?format=csv` on reports.
Status codes: 201 created, 200 for an idempotent replay, 401 unauthenticated, 402 plan limit reached,
403 forbidden, 404 not found (also for other tenants' ids), 409 conflict / already checked in, 422 validation
or GPS rejection, 429 rate limited.

**Check-in response** (`POST /attendance/check-in/`), which the UI renders directly:

```json
{ "state": "CHECK_IN_SUCCESS | GPS_ACCURACY_LOW | OUTSIDE_GEOFENCE | CHECK_IN_FAILED",
  "code": "OK | GEOFENCE_BOUNDARY | OUTSIDE_GEOFENCE | ALREADY_CHECKED_IN | CONSENT_REQUIRED | …",
  "message": "human readable", "office_name": "Bishkek HQ", "radius_m": 100, "max_accuracy_m": 50,
  "distance_m": 35.0, "accuracy_m": 12, "zone": "INSIDE", "session_id": 9, "record_id": 3,
  "pending_approval": false, "recorded_at": "client fix time", "received_at": "server time", "duplicate": false }
```

---

## 4. GPS geofencing engine

1. **Browser:** `navigator.geolocation.getCurrentPosition({enableHighAccuracy: true, timeout: 15000, maximumAge: 0})`.
   It reads latitude, longitude, accuracy and timestamp. The client computes a preview with the same
   rule, only to guide the user. The client never sends a distance or a status.
2. **Server validation** (`location_service.admit_event`):
   - Coordinate range, (0,0) "null island", accuracy > 0 and ≤ the configured sanity limit.
   - Timestamp not in the future (clock skew tolerance) and not older than the maximum age.
   - Consent recorded at that time; registered device (browsers auto-register a random device id).
   - Inside the scheduled window (shift ± margins). Outside the window nothing is stored.
   - Idempotency by `event_uuid`, plus same-device/same-timestamp/same-type duplicate detection.
3. **Spoofing indicators:** impossible speed between consecutive fixes (beyond what both accuracies can
   explain), mock-location flag, shared devices, and repeated failed check-in attempts (job). The event is
   excluded and an **anomaly for human review** is created. No automatic penalty is applied.
4. **Conservative zone rule** per office:
   `inside ⇔ distance + accuracy ≤ radius`, `outside ⇔ distance − accuracy > radius`, otherwise **UNCERTAIN**.
   Accuracy worse than the office's `max_accuracy` is also UNCERTAIN. Check-in returns
   `GPS_ACCURACY_LOW` and asks the employee to retry.
5. **Explicit check-in** succeeds only when the result is INSIDE. Check-out is allowed anywhere by default
   (the location is still recorded) or only inside if `checkout_requires_geofence`.
6. **Presence checks** (optional): while the attendance screen is open during a work session, the app
   refreshes the fix every 30–60 s. A hysteresis state machine (N consecutive fixes over a stability window)
   updates presence for monitoring. Only if `auto_geofence_attendance` is enabled do stable transitions
   open or close sessions automatically. The default is explicit check-in.
7. **Offline:** check-ins made offline are stored in IndexedDB with the client fix time, shown as
   **pending**, and synced in order on reconnect. The server validates them like any other event and
   records `received_at`. Delays over 15 min raise an informational `DELAYED_SYNC` anomaly.

## 5. Attendance calculation

Per work date (the shift's start date in the office or organization timezone; DST-aware via `zoneinfo`):

- `late = max(0, first_check_in − scheduled_start − grace)`. Example: shift 09:00, grace 5, arrival 09:13 → **8**. This exact case is tested.
- Early leave, worked time (minus unpaid breaks), break minutes, `overtime = max(0, worked − scheduled − threshold)`.
- Statuses: PRESENT, LATE, HALF_DAY, INCOMPLETE (no checkout by window end; checkout suggested for
  confirmation), ON_LEAVE, PENDING_CONFIRMATION, ABSENT, LOCATION_UNAVAILABLE.
- **No GPS ≠ absent:** ABSENT is only set when the employee's device produced location signals during the
  window. Otherwise the day is LOCATION_UNAVAILABLE and flagged for HR review.
- Multiple sessions per day, lunch breaks, temporary exits (expire after the policy limit; the session
  then closes at the time the employee left), business trips (count as work), overnight shifts, and
  multiple offices are all supported.
- Confirmation policies: **AUTOMATIC** (default; disputes allowed), **EMPLOYEE_CONFIRMATION** (an explicit
  check-in counts as the confirmation), **MANAGER_APPROVAL** (a manager approves; nobody approves
  their own attendance).
- Corrections and disputes are reviewed by HR or managers, applied transactionally, and audit-logged
  with before/after values.

## 6. Automation (Celery beat → worker)

| Job | Every | What |
|---|---|---|
| `process_delayed_events` | 1 min | Retry GPS events whose processing failed (stored as PENDING, never lost) |
| `deliver_notifications` | 30 s | Outbox: e-mail delivery when SMTP is configured; in-app always |
| `send_attendance_reminders` | 2 min | Check-in reminder before shift start; check-out reminder after shift end |
| `resolve_sessions` | 2 min | Expire breaks and temporary exits; close sessions whose window ended (incomplete) |
| `recalculate_open_records` | 5 min | Refresh live working hours |
| `detect_missing_checkins` | 5 min | Notify the employee and record an anomaly once per day |
| `remind_pending_confirmations` | 5 min | Pending approvals and checkouts |
| `finalize_days` | 10 min | Final status after each shift window (per employee timezone) |
| `detect_suspicious_location_events` | 10 min | Repeated failed check-in attempts |
| `notify_hr_anomalies` | 15 min | Digest to HR and the department's managers |
| `generate_daily/weekly/monthly_reports` | hourly | Snapshot each org's completed period in its own timezone (idempotent) |
| `purge_old_coordinates` | 6 h | Data retention: null raw coordinates after N days (derived audit fields kept) |

## 7. Security & privacy

- **Tenant isolation:** the organization always comes from the authenticated user row, never from request
  input. Every query is scoped. Other tenants' ids return 404. Covered by tests.
- **RBAC:** OWNER, ADMIN, HR, MANAGER (own departments only), EMPLOYEE (self only), and ACCOUNTANT
  (org-wide read of attendance and reports; no edits, approvals or monitoring). See `permissions/rbac.py`.
- **Auth:** bcrypt (SHA-256 pre-hash); 30-min JWT access token kept in memory; refresh token in an
  **httpOnly SameSite=Strict cookie** (`Secure` in production) with **rotation and reuse detection**
  (reusing a rotated token revokes the whole family). `token_version` revokes everything on password
  change or deactivation. Logout revokes the token family.
- **Google OAuth:** OIDC ID token verified server-side (signature via Google JWKS, `aud`, `iss`,
  `email_verified`, nonce, plus `state` checked client-side). It also activates invited users.
- **Rate limiting:** Redis-backed. Login is limited per IP and account, refresh per token family, with a
  generous per-IP ceiling (offices share a NAT IP), plus GPS endpoint and general per-user limits and an
  Nginx `limit_req`.
- **Other protections:** CORS allow-list, security headers (incl. `Permissions-Policy: geolocation=(self)`),
  input validation (Pydantic v2), idempotent GPS events, and audit logs for configuration, auth, consent,
  corrections and approvals.
- **Location privacy:**
  - Location is collected only on explicit check-in/out, or while the attendance screen is open during
    an active work session, and only inside the scheduled window.
  - Recorded consent is required, and withdrawal notifies HR.
  - A visible indicator shows when location is read.
  - Admins see presence, distance and accuracy only, never coordinates or trails.
  - Employees can see their own history.
  - Raw coordinates are purged after `location_retention_days` (default 90).

## 8. PWA

Web app manifest (standalone; 192, 512 and maskable icons; shortcuts) and a service worker (offline app
shell; immutable assets cache-first; OSM tiles stale-while-revalidate; **the API is never cached**). Also:
install prompt and per-platform install instructions on Profile, a network status indicator with a
pending count, and an IndexedDB offline queue with ordered retry on reconnect, focus and every 30 s.
One bad item never blocks the queue: 4xx is final and removed, 5xx or network errors are retried.

---

## 9. Running locally (development)

```bash
# Backend
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
export GEOATTEND_DATABASE_URL=postgresql+psycopg://user:pass@localhost/geoattend   # or sqlite:///./dev.db
alembic upgrade head
uvicorn app.main:app --reload                       # http://localhost:8000/api/docs
celery -A app.tasks.celery_app worker -l info       # optional (needs Redis)
celery -A app.tasks.celery_app beat -l info

# Frontend (proxies /api to :8000)
cd frontend && npm ci && npm run dev                # http://localhost:5173
```

Geolocation works on `http://localhost`. Any other host needs **HTTPS**.

## 10. Production deployment (Docker Compose)

```bash
cp .env.example .env     # set POSTGRES_PASSWORD, GEOATTEND_SECRET_KEY, GEOATTEND_FRONTEND_URL, CORS, cookie_secure=true
docker compose up -d --build
docker compose ps        # db, redis, api, worker healthy; web on ${HTTP_PORT}
```

- Services: `db` (postgis/postgis:16-3.4, volume `pgdata`), `redis` (AOF volume), `api` (runs
  `alembic upgrade head`, then uvicorn), `worker`, `beat`, `web` (Nginx serving the PWA and proxying `/api`).
  All have health checks.
- **TLS is mandatory for browser geolocation.** Terminate HTTPS at a load balancer or in the web container
  (`deploy/nginx/tls.conf.example`), set `GEOATTEND_COOKIE_SECURE=true`, and keep the CORS origin exact.
- Google sign-in: create an OAuth "Web application" client with redirect URI
  `https://<domain>/auth/google/callback`, and set `GEOATTEND_GOOGLE_CLIENT_ID` and `VITE_GOOGLE_CLIENT_ID`
  (build arg).
- Backups: `docker compose exec db pg_dump -U geoattend geoattend > backup.sql`. Upgrades:
  `docker compose up -d --build` (migrations run automatically at API start).
- Every environment variable is documented in `.env.example`.
- Scaling: run several `api` replicas; the rate limiter and Celery are Redis-backed; run exactly one `beat`.
- Map tiles: public OSM tiles fall under the OSM tile usage policy. For heavy traffic set `VITE_MAP_TILES`
  to your own or a commercial OSM tile server.

## 11. Tests

```bash
cd backend && pytest -q                                           # SQLite
TEST_DATABASE_URL=postgresql+psycopg://…/geoattend_test pytest -q # PostgreSQL (+ PostGIS cross-check)
cd frontend && npm test && npm run typecheck && npm run build
```

| Suite | Result |
|---|---|
| Backend, PostgreSQL 16 + PostGIS 3.4 | **148 passed** (incl. 25 automatic-attendance scenarios) |
| Backend, SQLite | **147 passed, 1 skipped** (PostGIS-only test) |
| Frontend, Vitest + React Testing Library | **58 passed**; `tsc` clean; production build OK |
| End-to-end, Chromium (Playwright), against both `vite preview` and the full Docker Compose stack | Passed (steps below) |

Backend coverage:
- Authentication: JWT expiry, revocation, refresh rotation and reuse detection, logout cookie, Google OAuth (mocked JWKS identity), invitations.
- Tenant isolation, RBAC (manager departments, accountant read-only, employee self-only).
- GPS validation, geofence boundary cases, accuracy and uncertainty, spoofing, idempotency, concurrency (threaded duplicate submissions; DB partial unique index).
- Attendance calculation: the 09:13 → 8 min example, lunch, temporary exits, multiple sessions, overnight, DST, early leave, overtime, half day.
- Policies (automatic, employee, manager approval), corrections and disputes, leave and business trips, missing GPS → LOCATION_UNAVAILABLE, offline sync and delayed processing, plan limits, reports, CSV, jobs, retention, audit.

Frontend coverage: check-in flow (permission prompt, granted/inside → success, outside, server
GPS_ACCURACY_LOW → retry, denied, offline → pending queue, consent gate, check-out), geofence math,
offline queue semantics, API error handling and token refresh, Zod form validation, and responsive
navigation and role menus.

End-to-end steps: register a company through the UI → create an office → invite an employee → the
employee accepts on an emulated Pixel 7 → consent → INSIDE → check-in accepted → check-out → a second
employee 600 m away is rejected (OUTSIDE_GEOFENCE) → an offline check-in is queued as pending and synced
on reconnect → admin dashboard, attendance, monitoring (light and dark) → service worker registered.
Screenshots are in `docs/screenshots/`.

---

## Automatic Attendance Mode / Режим автоматического учёта

**EN.** With `attendance_mode = AUTOMATIC`, employees never press Check-in/Check-out. While the Attendance screen is
open, the browser's `watchPosition()` (fallback `getCurrentPosition()`) delivers fixes and the page sends one
presence check every `presence_interval_seconds` (default 30 s) to `POST /attendance/presence-check/`.

**RU.** В режиме `AUTOMATIC` сотрудник не нажимает Check-in/Check-out. Пока открыт экран Attendance, браузер
(`watchPosition()`, резервно `getCurrentPosition()`) получает координаты, и страница каждые 30 с отправляет
проверку присутствия. Сервер сам считает расстояние (Haversine) до всех назначенных офисов и определяет зону.

| Event | Rule (defaults) |
|---|---|
| AUTO_CHECKIN | 2 consecutive validated INSIDE readings, no live session, shift (or unscheduled day if allowed) |
| TEMPORARY_EXIT | 3 consecutive validated OUTSIDE readings before *shift end − checkout grace (15 min)*; session kept |
| RETURN_TO_OFFICE | 2 INSIDE readings within the maximum absence (30 min); same session resumes; exits ≤ 10 min (grace) are counted as work |
| FINAL_CHECKOUT | confirmed exit after *shift end − 15 min*; or job at *shift end + automatic closure timeout (120 min)* → checkout at last validated presence (to be confirmed) |
| Not returned | absence > maximum → session ends at the exit time; the exit is kept (`NOT_RETURNED`) |
| OFFICE_SWITCH | moving between assigned offices keeps one session (`office_id` updated, event logged); overlapping geofences → primary office wins (`IGNORED_OVERLAP` for the other) |

Never acted upon: inaccurate readings (`GPS_INACCURATE`, accuracy > office max), missing GPS, closed tab,
lost connection (→ `STALE` / `LOCATION_UNAVAILABLE`, session kept), and measurements older than the stale
threshold (`STALE_MEASUREMENT`, not replayed). Check-in/out are atomic: per-employee row lock, the partial
unique index allows one live session, and `event_uuid` makes every request idempotent.

**Modes:** `MANUAL` (default, unchanged: buttons; presence checks still feed Monitoring), `AUTOMATIC` (no
buttons; manual endpoints return `409 MANUAL_DISABLED`), `HYBRID` (automatic + manual buttons). Admin/HR can
override any session (`PATCH /attendance/sessions/{id}/`, reason required, audit log with old/new values);
managers request corrections; employees dispute.

**Example policy** (`PATCH /api/v1/attendance/policy/`, Admin):
```json
{ "attendance_mode": "AUTOMATIC", "automatic_detection_enabled": true, "automatic_checkin_enabled": true,
  "automatic_checkout_enabled": true, "automatic_resume_enabled": true, "presence_interval_seconds": 30,
  "default_max_accuracy_m": 50, "entry_confirmation_count": 2, "exit_confirmation_count": 3,
  "presence_stale_seconds": 120, "temporary_exit_grace_minutes": 10, "temporary_exit_max_minutes": 30,
  "checkout_grace_minutes": 15, "automatic_checkout_timeout_minutes": 120,
  "allow_unscheduled_attendance": false, "require_registered_device": true, "count_temporary_exit_as_work": false }
```

**Monitoring** (`GET /monitoring/employees/?filter=all|inside|outside|active|late|temporary_exit|stale|no_permission|no_office`,
`GET /monitoring/summary/`): zone (`INSIDE`, `OUTSIDE`, `LOCATION_DETECTED`, `STALE`, `UNKNOWN`, `LOCATION_DENIED`, `NO_OFFICE`),
session (`ACTIVE`, `TEMPORARY_EXIT`, `PENDING_CHECKOUT`, `COMPLETED`, `NOT_STARTED`), attendance status, distance, accuracy,
last update/activity, permission, check-in time, working duration. No coordinates; managers see only their departments;
the page polls every 30 s only while visible.

**Browser limits / Ограничения браузеров:** detection works only while the Attendance screen is open and in the
foreground (iOS Safari and Android Chrome suspend background tabs; `clearWatch` is called when hidden). There is no
background GPS, so automatic check-out of an employee who closed the tab happens only through the shift-end rules.
Indoor accuracy is often 20–100 m: tune radius and accuracy per office.

---

## 12. Completed features

- Multi-tenant workspaces: registration (company type, timezone), Google sign-in/registration,
  invitations, 6 roles, departments, manager scoping.
- Offices with a map editor (click to place, use my location, radius slider, max accuracy, enable/disable,
  timezone) and advanced geofence settings.
- Weekly schedules (overnight, breaks, grace, overtime threshold) with employee or department assignment.
- Server-verified GPS check-in/out and breaks; conservative accuracy rule; spoofing detection;
  idempotency; offline queue.
- Attendance engine: sessions, breaks, late, early leave, overtime, half day, incomplete, leave, business
  trips, LOCATION_UNAVAILABLE; three confirmation policies; disputes, corrections and approvals.
- Admin dashboard: 7 KPIs and 5 charts with date and department filters, all from the API. Plus
  monitoring (privacy-preserving), attendance table, 7 reports with CSV export, leave management,
  anomalies, notifications, settings, billing (plan limits enforced), audit log.
- Employee portal: check-in dashboard, attendance history with disputes, schedule, personal reports,
  leave requests, profile with location permission, consent and install status.
- Manager portal: team dashboard, team attendance, monitoring, approvals, corrections, leave, team reports.
- PWA, dark mode, responsive (mobile bottom nav, drawer), accessible Radix primitives.
- Celery automation in organization timezones; Docker Compose deployment with Nginx, PostGIS and Redis.

## Limitations

- **No background tracking.** Browsers cannot reliably read GPS while the page is closed or backgrounded,
  and installing the PWA does not change that. Attendance relies on explicit check-in/out. Presence
  checks run only while the screen is open.
- **GPS can be inaccurate or spoofed.** Indoor readings of ±30–100 m are common, which is why the rule
  is conservative and asks for a retry. Browsers expose no mock-location flag, and desktop browsers often
  locate by Wi-Fi/IP. Speed, sharing and repeated-attempt heuristics raise anomalies but cannot prove
  spoofing, and nothing is penalized automatically.
- **HTTPS is required** for geolocation outside `localhost`.
- **Offline check-ins depend on the device clock.** Old offline events are rejected after
  `max_event_age_hours`, and long delays are flagged.
- **Billing:** plans and limits are enforced, but **no payment provider is integrated**. Plan changes
  are applied by the owner and audit-logged.
- **Notifications:** in-app plus e-mail (SMTP). Web Push is not implemented.
- **Email delivery:** without SMTP, HR copies the one-time invitation link shown after inviting.
- **Distances:** computed with Haversine (spherical Earth). PostGIS is installed and the test suite
  verifies agreement with `ST_DistanceSphere` within 0.1%, but queries don't use spatial indexes; at
  per-employee office counts this is not a bottleneck.
- **Real devices:** the E2E suite emulates geolocation in Chromium. It has not been run on physical
  Android or iOS devices, so test those before rollout (permission prompts and accuracy vary by OS and
  browser).
- **Docker images:** built and run end to end in this environment, using Docker Hub mirror base images
  and a sandbox-only CA overlay. The shipped Dockerfiles are the standard ones.

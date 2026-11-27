export type Role = "OWNER" | "ADMIN" | "HR" | "MANAGER" | "EMPLOYEE" | "ACCOUNTANT";
export type AttendanceStatus =
  | "PRESENT" | "LATE" | "ABSENT" | "HALF_DAY" | "INCOMPLETE" | "ON_LEAVE" | "PENDING_CONFIRMATION" | "LOCATION_UNAVAILABLE" | "UNSCHEDULED";

export interface Me {
  id: number; email: string; full_name: string; role: Role; organization_id: number; organization_name: string;
  organization_timezone: string; subscription_plan: string; employee_id: number | null; managed_department_ids: number[];
  has_password: boolean; google_linked: boolean;
}
export interface TokenPair { access_token: string; refresh_token: string; expires_in: number }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface Department { id: number; name: string; employee_count: number }
export interface Organization { id: number; name: string; slug: string; timezone: string; subscription_plan: string; company_type: string; is_active: boolean; created_at: string }

export interface Geofence {
  radius_m: number; max_accuracy_m: number; enabled: boolean; entry_detection_enabled: boolean; exit_detection_enabled: boolean;
  required_consecutive: number; stability_window_seconds: number; entry_buffer_m: number; exit_buffer_m: number; updated_at: string;
}
export interface Office {
  id: number; name: string; address: string | null; latitude: number; longitude: number; timezone: string; is_active: boolean;
  radius: number; max_accuracy: number; geofence: Geofence; employee_ids: number[]; created_at: string;
}
export interface Employee {
  id: number; user_id: number; full_name: string; email: string; employee_code: string; position: string | null; employment_status: string;
  hired_at: string | null; department_id: number | null; department_name: string | null; primary_office_id: number | null; office_ids: number[];
  role: Role; managed_department_ids: number[]; is_active: boolean; invite_pending: boolean; consent_granted: boolean | null;
  location_permission: string | null; created_at: string; invite_url?: string | null;
}
export interface ScheduleDay { weekday: number; is_working_day: boolean; start_time: string | null; end_time: string | null; break_start: string | null; break_end: string | null }
export interface Schedule { id: number; name: string; grace_period_minutes: number; early_leave_grace_minutes: number; overtime_threshold_minutes: number; is_active: boolean; days: ScheduleDay[] }
export interface Assignment { id: number; schedule_id: number; employee_id: number | null; department_id: number | null; effective_from: string; effective_to: string | null }
export interface Shift { work_date: string; start: string; end: string; break_start: string | null; break_end: string | null; timezone: string; schedule_id: number; tracking_window_start: string; tracking_window_end: string }

export interface AttendanceRecord {
  id: number; employee_id: number; employee_name: string | null; department_name: string | null; office_id: number | null; office_name: string | null;
  work_date: string; timezone: string; scheduled_start: string | null; scheduled_end: string | null; scheduled_minutes: number;
  actual_check_in: string | null; actual_check_out: string | null; late_minutes: number; early_departure_minutes: number;
  worked_minutes: number; break_minutes: number; overtime_minutes: number; status: AttendanceStatus; is_finalized: boolean; is_confirmed: boolean;
  early_arrival_minutes: number; presence_minutes: number; temporary_exit_minutes: number; is_unscheduled: boolean;
}
export interface Break { id: number; type: string; is_paid: boolean; started_at: string; ended_at: string | null; expires_at: string; detection_method: string; outcome: string; duration_minutes: number | null }
export interface Session {
  id: number; office_id: number | null; status: string; confirmation: string; source: string; check_in_at: string; detected_at: string | null;
  confirmed_at: string | null; check_out_at: string | null; close_reason: string | null; breaks: Break[]; duration_minutes: number | null; approved_by_id: number | null;
  gross_minutes: number | null; detection_method: string; check_in_accuracy_m: number | null;
}
export interface RecordDetail extends AttendanceRecord { sessions: Session[]; pending_confirmation: boolean; pending_checkout: boolean }

export interface OfficeFence { id: number; name: string; latitude: number; longitude: number; radius_m: number; max_accuracy_m: number; timezone: string }
export interface Today {
  work_date: string | null;
  shift: { start: string; end: string; break_start: string | null; break_end: string | null; timezone: string; grace_period_minutes: number; tracking_window_start: string; tracking_window_end: string } | null;
  record: RecordDetail | null;
  location: { presence: string; office_id: number | null; distance_m: number | null; accuracy_m: number | null; last_update: string | null; session_status: string | null };
  offices: OfficeFence[];
  actions: {
    window_open: boolean; can_check_in: boolean; can_check_out: boolean; can_start_break: boolean; can_end_break: boolean; live_session_id: number | null;
    live_status: string | null; confirmation_policy: string; checkout_requires_geofence: boolean; consent_granted: boolean;
  };
  server_time: string;
}
export interface GpsActionResult {
  state: "CHECK_IN_SUCCESS" | "CHECK_OUT_SUCCESS" | "GPS_ACCURACY_LOW" | "OUTSIDE_GEOFENCE" | "CHECK_IN_FAILED" | "CHECK_OUT_FAILED";
  code: string; message: string; office_id: number | null; office_name: string | null; radius_m: number | null; max_accuracy_m: number | null;
  distance_m: number | null; accuracy_m: number | null; zone: string | null; session_id: number | null; record_id: number | null; attendance_status: string | null;
  pending_approval: boolean; recorded_at: string | null; received_at: string | null; duplicate: boolean;
}
export interface TeamRow {
  employee_id: number; employee_name: string; department_name: string | null; office_name: string | null; scheduled_start: string | null;
  scheduled_end: string | null; actual_check_in: string | null; actual_check_out: string | null; worked_minutes: number; late_minutes: number;
  status: string; record_id: number | null; presence: string;
}
export interface Dashboard {
  date: string; is_today: boolean; total_employees: number; scheduled_today: number; present: number; late: number; absent: number; missing_check_ins: number;
  inside_office: number; outside_office: number; unconfirmed: number; location_unavailable: number; on_leave: number; open_anomalies: number;
  pending_corrections: number; avg_working_minutes: number; overtime_minutes: number;
}
export interface TrendPoint { date: string; records: number; present: number; late: number; absent: number; on_leave: number; location_unavailable: number; avg_worked_minutes: number; overtime_minutes: number; late_minutes: number; attendance_rate: number | null }
export interface DeptRow { department: string; employees: number; records: number; attendance_rate: number | null; punctuality_rate: number | null; late: number; absent: number; avg_worked_minutes: number; overtime_minutes: number }
export interface MonitoringRow {
  employee_id: number; employee_name: string; department_name: string | null; office_id: number | null; office_name: string | null; presence: string;
  last_zone: string | null; distance_m: number | null; accuracy_m: number | null; last_update: string | null; is_fresh: boolean;
  location_permission: string | null; consent_granted: boolean; session_status: string | null;
}
export interface Correction {
  id: number; record_id: number; employee_id: number; employee_name: string | null; work_date: string | null; type: string; requested_check_in: string | null;
  requested_check_out: string | null; reason: string; status: string; reviewed_at: string | null; review_comment: string | null; created_at: string;
}
export interface Approval { record_id: number; session_id: number; employee_id: number; employee_name: string; department_name: string | null; work_date: string; check_in_at: string; check_out_at: string | null; office_name: string | null; timezone: string }
export interface Anomaly { id: number; employee_id: number; employee_name: string | null; type: string; severity: string; status: string; work_date: string | null; details: Record<string, unknown> | null; detected_at: string }
export interface LeaveRequest { id: number; employee_id: number; employee_name: string | null; type: string; status: string; starts_at: string; ends_at: string; reason: string | null; reviewed_at: string | null }
export interface Settings {
  confirmation_policy: "AUTOMATIC" | "EMPLOYEE_CONFIRMATION" | "MANAGER_APPROVAL"; checkout_policy: "AUTO_CLOSE" | "REQUIRE_CONFIRMATION";
  default_radius_m: number; default_max_accuracy_m: number; required_consecutive: number; stability_window_seconds: number; entry_buffer_m: number;
  exit_buffer_m: number; max_reasonable_accuracy_m: number; max_speed_mps: number; max_event_age_hours: number; require_registered_device: boolean;
  pre_shift_tracking_minutes: number; post_shift_tracking_minutes: number; location_retention_days: number; temporary_exit_max_minutes: number;
  count_temporary_exit_as_work: boolean; lunch_detection_tolerance_minutes: number; half_day_ratio: number; missing_checkin_after_minutes: number;
  confirmation_reminder_minutes: number; location_fresh_minutes: number; auto_geofence_attendance: boolean; checkout_requires_geofence: boolean; checkin_reminder_minutes: number;
  presence_stale_seconds: number; attendance_mode: AttendanceMode; automatic_detection_enabled: boolean; automatic_checkin_enabled: boolean;
  automatic_checkout_enabled: boolean; automatic_resume_enabled: boolean; presence_interval_seconds: number; entry_confirmation_count: number;
  exit_confirmation_count: number; temporary_exit_grace_minutes: number; checkout_grace_minutes: number; automatic_checkout_timeout_minutes: number;
  allow_unscheduled_attendance: boolean;
}
export interface Plan { code: string; name: string; monthly_price_usd: number | null; max_employees: number | null; max_offices: number | null; features: string[] }
export interface Billing { plan: Plan; usage: { employees: number; offices: number }; plans: Plan[]; payment_provider_connected: boolean }
export interface AppNotification { id: number; type: string; title: string; body: string; read_at: string | null; created_at: string }
export interface AuditEntry { id: number; actor_user_id: number | null; action: string; entity_type: string; entity_id: string | null; changes: Record<string, unknown> | null; created_at: string }
export interface Consent { granted: boolean; consent_version: string | null; updated_at: string | null; required_version: string; policy_text: string }

// ---------------- Automatic attendance ----------------
export type AttendanceMode = "MANUAL" | "AUTOMATIC" | "HYBRID";
export type ZoneStatus = "INSIDE" | "OUTSIDE" | "LOCATION_DETECTED" | "STALE" | "UNKNOWN" | "LOCATION_DENIED" | "NO_OFFICE";
export type SessionState = "ACTIVE" | "TEMPORARY_EXIT" | "PENDING_CHECKOUT" | "COMPLETED" | "NOT_STARTED";
export interface AttendancePolicy {
  attendance_mode: AttendanceMode; automatic_detection_enabled: boolean; automatic_checkin_enabled: boolean; automatic_checkout_enabled: boolean;
  automatic_resume_enabled: boolean; presence_interval_seconds: number; default_max_accuracy_m: number; entry_confirmation_count: number;
  exit_confirmation_count: number; presence_stale_seconds: number; temporary_exit_grace_minutes: number; temporary_exit_max_minutes: number;
  checkout_grace_minutes: number; automatic_checkout_timeout_minutes: number; allow_unscheduled_attendance: boolean; require_registered_device: boolean;
  count_temporary_exit_as_work: boolean; confirmation_policy: string; automatic_attendance: boolean; manual_actions_allowed: boolean;
}
export interface PresenceView {
  zone_status: ZoneStatus; reason: string; office_id: number | null; assigned_office_ids: number[]; distance_m: number | null; accuracy_m: number | null;
  last_update: string | null; last_validated_at: string | null; validated_zone: string | null; last_activity: string | null; permission: string | null;
  consent_granted: boolean; session_status: SessionState; session_id: number | null; record_id: number | null; attendance_status: string;
  check_in_time: string | null; check_out_time: string | null; working_minutes: number; late_minutes: number; temporary_exit_started_at: string | null;
  temporary_exit_minutes: number; is_unscheduled: boolean;
}
export interface TemporaryExit { id: number; type: string; exited_at: string; returned_at: string | null; outcome: string; duration_minutes: number | null; counted_as_working_time: boolean; detection_method: string }
export interface AutoSession {
  id: number; employee_id: number; office_id: number | null; record_id: number; status: string; detection_method: string; confirmation: string;
  started_at: string; ended_at: string | null; close_reason: string | null; check_in_accuracy_m: number | null; check_in_device_id: string | null;
  total_minutes: number | null; payable_minutes: number | null; temporary_exits: TemporaryExit[];
}
export interface AutoRecord {
  id: number; work_date: string; timezone: string; scheduled_start: string | null; scheduled_end: string | null; actual_check_in: string | null;
  actual_check_out: string | null; late_minutes: number; early_arrival_minutes: number; early_departure_minutes: number; worked_minutes: number;
  payable_minutes: number; presence_minutes: number; temporary_exit_minutes: number; break_minutes: number; overtime_minutes: number; status: string;
  is_unscheduled: boolean; sessions: AutoSession[];
}
export interface AutomaticPayload {
  ui_state: string; message: string; server_time: string; policy: AttendancePolicy; presence: PresenceView;
  office: { id: number; name: string; radius_m: number; max_accuracy_m: number } | null;
  reading: { result: string; reason: string | null; zone: string | null; distance_m: number | null; accuracy_m: number | null; effects?: string[] | null; confirmation?: { target: string; readings: number; required: number } | null } | null;
  record?: AutoRecord | null;
  events?: { type: string; effect: string | null; office_id: number; occurred_at: string; readings: number; note: string | null }[];
}
export interface MonitoringEmployee {
  employee_id: number; employee_name: string; position: string | null; department_name: string | null; assigned_offices: string[]; office_id: number | null;
  office_name: string | null; zone_status: ZoneStatus; zone_reason: string; distance_m: number | null; accuracy_m: number | null; last_update: string | null;
  last_activity: string | null; permission: string | null; consent_granted: boolean; attendance_status: string; session_status: SessionState;
  check_in_time: string | null; check_out_time: string | null; working_minutes: number; late_minutes: number; temporary_exit_started_at: string | null;
  temporary_exit_minutes: number;
}
export interface MonitoringSummary {
  generated_at: string; total_employees: number; currently_inside: number; currently_outside: number; active_sessions: number; late_today: number;
  temporary_exits: number; location_unavailable: number; stale: number; no_permission: number; no_office: number; stale_after_seconds: number;
}

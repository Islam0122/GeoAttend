"""automatic attendance mode + explicit monitoring presence

- organization_settings: attendance mode and automatic-detection policy
- geofence_states: latest server-validated presence per office (monitoring)
- geofence_transitions.attendance_effect: TEMPORARY_EXIT / RETURN_TO_OFFICE / FINAL_CHECKOUT / OFFICE_SWITCH ...
- attendance_records: early arrival, physical presence and temporary-exit minutes, unscheduled flag
- attendance_sessions: detection method, check-in accuracy/device, gross minutes
- attendance_breaks (temporary exits): detection method, outcome, duration — exits are never deleted
- device_registrations.permission_updated_at

Revision ID: 0003_automatic_attendance
Revises: 0002_web_pwa
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_automatic_attendance"
down_revision = "0002_web_pwa"
branch_labels = None
depends_on = None

SETTINGS = [
    ("presence_stale_seconds", sa.Integer(), "120"),
    ("attendance_mode", sa.String(32), "MANUAL"),
    ("automatic_detection_enabled", sa.Boolean(), sa.true()),
    ("automatic_checkin_enabled", sa.Boolean(), sa.true()),
    ("automatic_checkout_enabled", sa.Boolean(), sa.true()),
    ("automatic_resume_enabled", sa.Boolean(), sa.true()),
    ("presence_interval_seconds", sa.Integer(), "30"),
    ("entry_confirmation_count", sa.Integer(), "2"),
    ("exit_confirmation_count", sa.Integer(), "3"),
    ("temporary_exit_grace_minutes", sa.Integer(), "10"),
    ("checkout_grace_minutes", sa.Integer(), "15"),
    ("automatic_checkout_timeout_minutes", sa.Integer(), "120"),
    ("allow_unscheduled_attendance", sa.Boolean(), sa.false()),
]


def upgrade() -> None:
    with op.batch_alter_table("organization_settings") as b:
        for name, type_, default in SETTINGS:
            b.add_column(sa.Column(name, type_, nullable=False, server_default=default))
    # Backwards compatible: organizations that enabled the legacy automatic flag become HYBRID; others stay MANUAL.
    op.execute("UPDATE organization_settings SET attendance_mode = 'HYBRID' WHERE auto_geofence_attendance = true")

    with op.batch_alter_table("geofence_states") as b:
        b.add_column(sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("last_validated_zone", sa.String(32), nullable=True))
        b.add_column(sa.Column("last_validated_distance_m", sa.Float(), nullable=True))
        b.add_column(sa.Column("last_validated_accuracy_m", sa.Float(), nullable=True))
        b.add_column(sa.Column("last_event_type", sa.String(16), nullable=True))
    # Readings the server already classified INSIDE/OUTSIDE were hidden behind hysteresis as UNKNOWN.
    op.execute(
        "UPDATE geofence_states SET last_validated_at = last_recorded_at, last_validated_zone = last_zone, "
        "last_validated_distance_m = last_distance_m, last_validated_accuracy_m = last_accuracy_m "
        "WHERE last_zone IN ('INSIDE', 'OUTSIDE') AND last_recorded_at IS NOT NULL"
    )

    with op.batch_alter_table("geofence_transitions") as b:
        b.add_column(sa.Column("attendance_effect", sa.String(32), nullable=True))

    with op.batch_alter_table("device_registrations") as b:
        b.add_column(sa.Column("permission_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE device_registrations SET permission_updated_at = last_seen_at")

    with op.batch_alter_table("attendance_records") as b:
        b.add_column(sa.Column("is_unscheduled", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("early_arrival_minutes", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("presence_minutes", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("temporary_exit_minutes", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE attendance_records SET presence_minutes = worked_minutes")

    with op.batch_alter_table("attendance_sessions") as b:
        b.add_column(sa.Column("gross_minutes", sa.Integer(), nullable=True))
        b.add_column(sa.Column("detection_method", sa.String(16), nullable=False, server_default="MANUAL"))
        b.add_column(sa.Column("check_in_accuracy_m", sa.Float(), nullable=True))
        b.add_column(sa.Column("check_in_device_id", sa.String(128), nullable=True))
    op.execute("UPDATE attendance_sessions SET detection_method = 'AUTOMATIC' WHERE enter_transition_id IS NOT NULL")
    op.execute("UPDATE attendance_sessions SET detection_method = 'CORRECTION' WHERE source = 'CORRECTION'")

    with op.batch_alter_table("attendance_breaks") as b:
        b.add_column(sa.Column("detection_method", sa.String(16), nullable=False, server_default="AUTOMATIC"))
        b.add_column(sa.Column("outcome", sa.String(16), nullable=False, server_default="OPEN"))
        b.add_column(sa.Column("duration_minutes", sa.Integer(), nullable=True))
    op.execute("UPDATE attendance_breaks SET outcome = 'RETURNED' WHERE ended_at IS NOT NULL")
    op.create_index("ix_geofence_states_emp_validated", "geofence_states", ["employee_id", "last_validated_at"])


def downgrade() -> None:
    op.drop_index("ix_geofence_states_emp_validated", table_name="geofence_states")
    with op.batch_alter_table("attendance_breaks") as b:
        for c in ("duration_minutes", "outcome", "detection_method"):
            b.drop_column(c)
    with op.batch_alter_table("attendance_sessions") as b:
        for c in ("check_in_device_id", "check_in_accuracy_m", "detection_method", "gross_minutes"):
            b.drop_column(c)
    with op.batch_alter_table("attendance_records") as b:
        for c in ("temporary_exit_minutes", "presence_minutes", "early_arrival_minutes", "is_unscheduled"):
            b.drop_column(c)
    with op.batch_alter_table("device_registrations") as b:
        b.drop_column("permission_updated_at")
    with op.batch_alter_table("geofence_transitions") as b:
        b.drop_column("attendance_effect")
    with op.batch_alter_table("geofence_states") as b:
        for c in ("last_event_type", "last_validated_accuracy_m", "last_validated_distance_m", "last_validated_zone", "last_validated_at"):
            b.drop_column(c)
    with op.batch_alter_table("organization_settings") as b:
        for name, _, _ in reversed(SETTINGS):
            b.drop_column(name)

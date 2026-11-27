"""web/PWA attendance: explicit check-in/out, plans, Google OAuth, refresh rotation, leave requests

Revision ID: 0002_web_pwa
Revises: 0001_initial
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_web_pwa"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _enable_postgis() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    available = bind.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'postgis'")).scalar()
    if available:
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def upgrade() -> None:
    _enable_postgis()

    # absence_periods -> leave_requests (data preserved)
    with op.batch_alter_table("absence_periods") as b:
        b.drop_index("ix_absence_periods_employee_id")
        b.drop_index("ix_absence_periods_organization_id")
    op.rename_table("absence_periods", "leave_requests")
    with op.batch_alter_table("leave_requests") as b:
        b.create_index("ix_leave_requests_employee_id", ["employee_id"])
        b.create_index("ix_leave_requests_organization_id", ["organization_id"])

    with op.batch_alter_table("organizations") as b:
        b.add_column(sa.Column("subscription_plan", sa.String(32), nullable=False, server_default="FREE"))
        b.add_column(sa.Column("company_type", sa.String(32), nullable=False, server_default="OTHER"))

    with op.batch_alter_table("organization_settings") as b:
        b.add_column(sa.Column("auto_geofence_attendance", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("checkout_requires_geofence", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("checkin_reminder_minutes", sa.Integer(), nullable=False, server_default="10"))

    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("google_sub", sa.String(64), nullable=True))
        b.create_unique_constraint("uq_users_google_sub", ["google_sub"])

    with op.batch_alter_table("employees") as b:
        b.add_column(sa.Column("employment_status", sa.String(32), nullable=False, server_default="ACTIVE"))
        b.add_column(sa.Column("hired_at", sa.Date(), nullable=True))

    with op.batch_alter_table("location_events") as b:
        b.add_column(sa.Column("event_type", sa.String(32), nullable=False, server_default="PRESENCE"))
        b.create_index("ix_location_events_emp_type_time", ["employee_id", "event_type", "recorded_at"])

    with op.batch_alter_table("attendance_records") as b:
        b.add_column(sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("attendance_sessions") as b:
        b.add_column(sa.Column("check_in_event_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("check_out_event_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("duration_minutes", sa.Integer(), nullable=True))
        b.add_column(sa.Column("approved_by_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_attendance_sessions_check_in_event_id_location_events", "location_events", ["check_in_event_id"], ["id"], ondelete="SET NULL")
        b.create_foreign_key("fk_attendance_sessions_check_out_event_id_location_events", "location_events", ["check_out_event_id"], ["id"], ondelete="SET NULL")
        b.create_foreign_key("fk_attendance_sessions_approved_by_id_users", "users", ["approved_by_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE", name="fk_refresh_tokens_organization_id_organizations"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_refresh_tokens_user_id_users"), nullable=False),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("family", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("jti", name="uq_refresh_tokens_jti"),
    )
    op.create_index("ix_refresh_tokens_family", "refresh_tokens", ["family"])
    op.create_index("ix_refresh_tokens_organization_id", "refresh_tokens", ["organization_id"])
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("attendance_sessions") as b:
        b.drop_constraint("fk_attendance_sessions_approved_by_id_users", type_="foreignkey")
        b.drop_constraint("fk_attendance_sessions_check_out_event_id_location_events", type_="foreignkey")
        b.drop_constraint("fk_attendance_sessions_check_in_event_id_location_events", type_="foreignkey")
        for c in ("approved_by_id", "duration_minutes", "check_out_event_id", "check_in_event_id"):
            b.drop_column(c)
    with op.batch_alter_table("attendance_records") as b:
        b.drop_column("is_confirmed")
    with op.batch_alter_table("location_events") as b:
        b.drop_index("ix_location_events_emp_type_time")
        b.drop_column("event_type")
    with op.batch_alter_table("employees") as b:
        b.drop_column("hired_at")
        b.drop_column("employment_status")
    with op.batch_alter_table("users") as b:
        b.drop_constraint("uq_users_google_sub", type_="unique")
        b.drop_column("google_sub")
    with op.batch_alter_table("organization_settings") as b:
        for c in ("checkin_reminder_minutes", "checkout_requires_geofence", "auto_geofence_attendance"):
            b.drop_column(c)
    with op.batch_alter_table("organizations") as b:
        b.drop_column("company_type")
        b.drop_column("subscription_plan")
    with op.batch_alter_table("leave_requests") as b:
        b.drop_index("ix_leave_requests_employee_id")
        b.drop_index("ix_leave_requests_organization_id")
    op.rename_table("leave_requests", "absence_periods")
    with op.batch_alter_table("absence_periods") as b:
        b.create_index("ix_absence_periods_employee_id", ["employee_id"])
        b.create_index("ix_absence_periods_organization_id", ["organization_id"])

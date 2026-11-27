"""Pure attendance calculation."""
from datetime import datetime, timedelta, timezone

from app.models.enums import AttendanceStatus as S
from app.models.enums import BreakType
from app.models.enums import SessionConfirmation as C
from app.models.enums import SessionStatus as SS
from app.services.calculation import BreakData, DayPolicy, SessionData, compute

D = datetime(2026, 11, 23, tzinfo=timezone.utc)
START, END = D.replace(hour=9), D.replace(hour=18)
POLICY = DayPolicy(scheduled_start=START, scheduled_end=END, scheduled_minutes=480, grace_period_minutes=10)


def sess(h_in, m_in, h_out=None, m_out=0, conf=C.AUTO_CONFIRMED, status=SS.CLOSED, breaks=()):
    return SessionData(conf, status if h_out is not None else SS.OPEN, D.replace(hour=h_in, minute=m_in),
                       D.replace(hour=h_out, minute=m_out) if h_out is not None else None, list(breaks))


def run(sessions, now=D.replace(hour=20), finalized=True, **kw):
    return compute(sessions, POLICY, now=now, finalized=finalized, on_leave=kw.get("on_leave", False), signal_available=kw.get("signal", True))


def test_on_time_within_grace():
    m = run([sess(9, 8, 18, 0, breaks=[BreakData(BreakType.LUNCH, False, D.replace(hour=13), D.replace(hour=14))])])
    assert m.late_minutes == 0 and m.status == S.PRESENT
    assert m.worked_minutes == 8 * 60 + 52 - 60
    assert m.break_minutes == 60 and m.early_departure_minutes == 0


def test_late_formula():
    # 09:25 arrival, grace 10 -> 15 late
    m = run([sess(9, 25, 18, 0)])
    assert m.late_minutes == 15 and m.status == S.LATE


def test_early_departure_and_half_day():
    m = run([sess(9, 0, 12, 0)])
    assert m.early_departure_minutes == 360
    assert m.status == S.HALF_DAY  # 180 < 480 * 0.5


def test_overtime():
    m = run([sess(9, 0, 20, 0)], now=D.replace(hour=21))
    assert m.worked_minutes == 660 and m.overtime_minutes == 180


def test_multiple_sessions_sum():
    m = run([sess(9, 0, 11, 0), sess(12, 0, 18, 0)])
    assert m.worked_minutes == 480 and m.actual_check_in == D.replace(hour=9) and m.actual_check_out == END


def test_temporary_exit_policy():
    brk = BreakData(BreakType.TEMPORARY_EXIT, False, D.replace(hour=11), D.replace(hour=11, minute=20))
    m = run([sess(9, 0, 18, 0, breaks=[brk])])
    assert m.worked_minutes == 520 and m.break_minutes == 20
    pol = DayPolicy(**{**POLICY.__dict__, "count_temporary_exit_as_work": True})
    m2 = compute([sess(9, 0, 18, 0, breaks=[brk])], pol, now=D.replace(hour=20), finalized=True, on_leave=False, signal_available=True)
    assert m2.worked_minutes == 540


def test_business_trip_counts_as_work():
    trip = BreakData(BreakType.BUSINESS_TRIP, True, D.replace(hour=10), D.replace(hour=17))
    assert run([sess(9, 0, 18, 0, breaks=[trip])]).worked_minutes == 540


def test_no_sessions_signal_vs_unavailable():
    assert run([], signal=True).status == S.ABSENT
    assert run([], signal=False).status == S.LOCATION_UNAVAILABLE
    assert run([], on_leave=True, signal=True).status == S.ON_LEAVE


def test_pending_confirmation_not_counted():
    m = run([sess(9, 0, 18, 0, conf=C.PENDING)], finalized=False)
    assert m.status == S.PENDING_CONFIRMATION and m.worked_minutes == 0


def test_live_session_uses_now_and_incomplete_when_finalized():
    m = run([sess(9, 0)], now=D.replace(hour=12), finalized=False)
    assert m.worked_minutes == 180 and m.status == S.PRESENT and m.actual_check_out is None
    m = run([SessionData(C.AUTO_CONFIRMED, SS.PENDING_CHECKOUT, D.replace(hour=9), D.replace(hour=17))], finalized=True)
    assert m.status == S.INCOMPLETE


def test_overnight_session_minutes():
    start, end = D.replace(hour=22), D.replace(hour=22) + timedelta(hours=8)
    pol = DayPolicy(scheduled_start=start, scheduled_end=end, scheduled_minutes=480, grace_period_minutes=5)
    m = compute([SessionData(C.AUTO_CONFIRMED, SS.CLOSED, start + timedelta(minutes=12), end)], pol, now=end + timedelta(hours=2),
                finalized=True, on_leave=False, signal_available=True)
    assert m.late_minutes == 7 and m.worked_minutes == 468 and m.status == S.LATE

"""Pure GPS math + hysteresis state machine."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.enums import GeofencePresence as P
from app.models.enums import Zone
from app.services import geo

T0 = datetime(2026, 11, 23, 3, 0, tzinfo=timezone.utc)
FENCE = geo.FenceParams(radius_m=100, max_accuracy_m=50)


def test_haversine_known_distances():
    # 1 degree of latitude ~ 111.2 km
    assert geo.haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=1e-3)
    # Bishkek -> Almaty ~ 196 km
    assert geo.haversine_m(42.8746, 74.5698, 43.2389, 76.8897) == pytest.approx(196_000, rel=0.02)
    assert geo.haversine_m(10, 10, 10, 10) == 0


@pytest.mark.parametrize("distance,accuracy,expected", [
    (20, 10, Zone.INSIDE),      # 30 <= 100
    (90, 10, Zone.INSIDE),      # 100 <= 100 (boundary)
    (95, 10, Zone.UNCERTAIN),   # 105 > 100 and 85 <= 100
    (130, 20, Zone.OUTSIDE),    # 110 > 100
    (110, 10, Zone.UNCERTAIN),  # 100 is not > 100
    (10, 60, Zone.UNCERTAIN),   # accuracy above geofence maximum
])
def test_classify(distance, accuracy, expected):
    assert geo.classify(distance, accuracy, FENCE) == expected


def test_classify_hysteresis_buffers():
    f = geo.FenceParams(radius_m=100, max_accuracy_m=50, entry_buffer_m=20, exit_buffer_m=30)
    assert geo.classify(75, 10, f) == Zone.UNCERTAIN   # 85 > 80 -> not confirmed inside
    assert geo.classify(65, 10, f) == Zone.INSIDE
    assert geo.classify(135, 10, f) == Zone.UNCERTAIN  # 125 <= 130 -> not confirmed outside
    assert geo.classify(145, 10, f) == Zone.OUTSIDE


@pytest.mark.parametrize("lat,lng,reason", [
    (91, 0, "COORDINATES_OUT_OF_RANGE"), (0, 181, "COORDINATES_OUT_OF_RANGE"), (-90.5, 10, "COORDINATES_OUT_OF_RANGE"),
    (0, 0, "NULL_ISLAND"), (float("nan"), 10, "INVALID_COORDINATES"), (float("inf"), 10, "INVALID_COORDINATES"),
])
def test_invalid_coordinates(lat, lng, reason):
    assert geo.validate_coordinates(lat, lng) == reason


def test_valid_coordinates_and_accuracy():
    assert geo.validate_coordinates(42.87, 74.56) is None
    assert geo.validate_accuracy(0, 1000) == "INVALID_ACCURACY"
    assert geo.validate_accuracy(-5, 1000) == "INVALID_ACCURACY"
    assert geo.validate_accuracy(5000, 1000) == "ACCURACY_UNREASONABLE"
    assert geo.validate_accuracy(12.5, 1000) is None


def test_suspicious_jump_detection():
    # 10 km in 30 s = 333 m/s
    d, v = geo.implied_speed_mps(42.0, 74.0, T0, 42.09, 74.0, T0 + timedelta(seconds=30))
    assert geo.is_suspicious_jump(d, v, 10, 10, max_speed_mps=70)
    # 300 m in 30 s with poor accuracy is explainable by accuracy
    d, v = geo.implied_speed_mps(42.0, 74.0, T0, 42.0027, 74.0, T0 + timedelta(seconds=30))
    assert not geo.is_suspicious_jump(d, v, 200, 150, max_speed_mps=70)
    # car speed is fine
    d, v = geo.implied_speed_mps(42.0, 74.0, T0, 42.009, 74.0, T0 + timedelta(seconds=60))
    assert not geo.is_suspicious_jump(d, v, 10, 10, max_speed_mps=70)


CFG = geo.StabilityConfig(required_consecutive=3, stability_window_seconds=60)


def run(zones, start=P.UNKNOWN, step=30):
    st = geo.PresenceState(start, None, 0, None)
    confirmed = []
    for i, z in enumerate(zones):
        r = geo.step(st, z, T0 + timedelta(seconds=i * step), CFG)
        st = r.state
        if r.confirmed:
            confirmed.append((r.confirmed, r.occurred_at))
    return st, confirmed


def test_entry_needs_three_readings_and_window():
    st, c = run([Zone.INSIDE, Zone.INSIDE])
    assert c == [] and st.presence == P.UNKNOWN and st.candidate_count == 2
    st, c = run([Zone.INSIDE] * 3)
    assert c == [(P.INSIDE, T0)]  # arrival = first reading of the streak
    # three readings within 20 s are not stable enough
    st, c = run([Zone.INSIDE] * 3, step=10)
    assert c == []
    st, c = run([Zone.INSIDE] * 7, step=10)
    assert c and c[0][0] == P.INSIDE


def test_uncertain_readings_neither_count_nor_reset():
    st, c = run([Zone.INSIDE, Zone.UNCERTAIN, Zone.INSIDE, Zone.UNCERTAIN, Zone.INSIDE])
    assert c == [(P.INSIDE, T0)]


def test_flapping_does_not_confirm():
    st, c = run([Zone.OUTSIDE, Zone.INSIDE, Zone.OUTSIDE, Zone.INSIDE, Zone.OUTSIDE, Zone.INSIDE], start=P.OUTSIDE)
    assert c == [] and st.presence == P.OUTSIDE


def test_exit_after_inside():
    st, c = run([Zone.OUTSIDE] * 3, start=P.INSIDE)
    assert c == [(P.OUTSIDE, T0)] and st.presence == P.OUTSIDE

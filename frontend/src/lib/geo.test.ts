import { describe, expect, it } from "vitest";
import { haversine, nearestOffice, previewZone } from "./geo";

describe("geofence preview (mirrors server rule)", () => {
  it("computes haversine distance", () => {
    expect(haversine(0, 0, 1, 0)).toBeGreaterThan(111_000);
    expect(haversine(0, 0, 1, 0)).toBeLessThan(111_400);
    expect(haversine(42.8746, 74.5698, 42.8746, 74.5698)).toBe(0);
  });
  it("classifies conservatively", () => {
    expect(previewZone(20, 10, 100, 50)).toBe("INSIDE_GEOFENCE");
    expect(previewZone(90, 10, 100, 50)).toBe("INSIDE_GEOFENCE"); // boundary: 100 <= 100
    expect(previewZone(95, 10, 100, 50)).toBe("GPS_ACCURACY_LOW"); // uncertain
    expect(previewZone(130, 20, 100, 50)).toBe("OUTSIDE_GEOFENCE");
    expect(previewZone(10, 60, 100, 50)).toBe("GPS_ACCURACY_LOW"); // accuracy worse than office max
  });
  it("picks the nearest office", () => {
    const fix = { latitude: 42.8746, longitude: 74.5698, accuracy: 5, timestamp: 0 };
    const r = nearestOffice(fix, [{ id: 1, latitude: 43, longitude: 75 }, { id: 2, latitude: 42.875, longitude: 74.57 }]);
    expect(r?.office.id).toBe(2);
  });
});

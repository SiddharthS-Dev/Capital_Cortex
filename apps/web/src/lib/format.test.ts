import { afterEach, describe, expect, it, vi } from "vitest";
import { date, daysUntil, isDateOnly, relativeDeadline } from "./format";

afterEach(() => vi.useRealTimers());

describe("plain-date deadlines (stored as midnight UTC)", () => {
  it("are recognised", () => {
    expect(isDateOnly("2026-10-15T00:00:00Z")).toBe(true);
    expect(isDateOnly("2026-10-15T00:00:00+00:00")).toBe(true);
    expect(isDateOnly("2026-10-15")).toBe(true);
    expect(isDateOnly("2026-10-06T15:00:00+00:00")).toBe(false);
  });
  it("show their own day in every time zone (was a day early west of UTC)", () => {
    expect(date("2026-10-15T00:00:00Z")).toMatch(/15/);
    expect(date("2026-10-15T00:00:00Z")).not.toMatch(/14/);
  });
});

describe("relativeDeadline", () => {
  it("counts calendar days, not 24-hour blocks", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 3, 20, 0)); // 3 Oct, 20:00 local
    expect(daysUntil(new Date(2026, 9, 4, 21, 0).toISOString())).toBe(1); // 25 h away is tomorrow, not "2d"
    expect(relativeDeadline("2026-10-03T00:00:00Z")).toBe("Due today");
    expect(relativeDeadline("2026-10-05T00:00:00Z")).toBe("2d left");
  });
  it("a timed deadline that passed earlier today is closed, not 'due today'", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 3, 20, 0));
    expect(relativeDeadline(new Date(2026, 9, 3, 12, 0).toISOString())).toBe("Closed today");
    expect(relativeDeadline(new Date(2026, 9, 2, 12, 0).toISOString())).toBe("Closed 1d ago");
  });
});

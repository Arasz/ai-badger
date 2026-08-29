import { describe, expect, test } from "bun:test";
import {
  BUN_LABEL_PREFIX,
  LAUNCHD_LABEL_PREFIX,
  MAX_CALENDAR_INTERVALS,
  calendarIntervals,
  plistFor,
  sanitizeTitle,
  schedulableJobs,
  staleLabels,
  xmlEscape,
  type CronJob,
} from "../cron/index.ts";

describe("noAgent defaults to true, as the docs have always claimed", () => {
  const jobs: CronJob[] = [
    { title: "no-field", schedule: "0 3 * * *", command: "echo a" },
    { title: "explicit-true", schedule: "0 3 * * *", command: "echo b", noAgent: true },
    { title: "explicit-false", schedule: "0 3 * * *", command: "echo c", noAgent: false },
  ];

  test("a job that omits noAgent is scheduled", () => {
    expect(schedulableJobs(jobs).map((j) => j.title)).toEqual(["no-field", "explicit-true"]);
  });

  test("only an explicit false opts a job out", () => {
    expect(schedulableJobs([{ title: "x", schedule: "0 3 * * *", command: "c", noAgent: false }]))
      .toEqual([]);
  });
});

describe("titles are sanitized, never silently mangled", () => {
  test("a plain title passes through", () => {
    expect(sanitizeTitle("daily-sync_2")).toBe("daily-sync_2");
  });

  test("anything outside [A-Za-z0-9_-] is rejected rather than stripped into a collision", () => {
    expect(sanitizeTitle("daily sync")).toBeNull();
    expect(sanitizeTitle("../../etc/passwd")).toBeNull();
    expect(sanitizeTitle("a.b")).toBeNull();
    expect(sanitizeTitle("")).toBeNull();
  });

  test("two titles that would collide after stripping are both rejected, not merged", () => {
    expect(sanitizeTitle("a b")).toBeNull();
    expect(sanitizeTitle("a.b")).toBeNull();
  });
});

describe("cron schedules translate into StartCalendarInterval dicts", () => {
  test("a daily job is one dict", () => {
    expect(calendarIntervals("0 3 * * *")).toEqual({ intervals: [{ Minute: 0, Hour: 3 }] });
  });

  test("a step expands across the hours it covers", () => {
    const result = calendarIntervals("*/15 * * * *");
    expect("intervals" in result && result.intervals).toHaveLength(96);
    expect("intervals" in result && result.intervals[0]).toEqual({ Minute: 0, Hour: 0 });
  });

  test("a comma list and a range both expand", () => {
    expect(calendarIntervals("0,30 2 * * *")).toEqual({
      intervals: [
        { Minute: 0, Hour: 2 },
        { Minute: 30, Hour: 2 },
      ],
    });
    const business = calendarIntervals("0 9-17 * * *");
    expect("intervals" in business && business.intervals).toHaveLength(9);
  });

  test("a restricted day-of-month becomes Day, a restricted weekday becomes Weekday", () => {
    expect(calendarIntervals("0 3 1 * *")).toEqual({ intervals: [{ Minute: 0, Hour: 3, Day: 1 }] });
    expect(calendarIntervals("0 3 * * 1")).toEqual({
      intervals: [{ Minute: 0, Hour: 3, Weekday: 1 }],
    });
  });

  test("a `*` day, month or weekday is omitted, which is launchd's own 'every'", () => {
    const result = calendarIntervals("0 3 * * *");
    expect("intervals" in result && Object.keys(result.intervals[0]!)).toEqual(["Minute", "Hour"]);
  });

  test("restricting day-of-month AND weekday is refused: cron ORs them, launchd ANDs them", () => {
    const result = calendarIntervals("0 3 1 * 1");
    expect("error" in result && result.error).toContain("day-of-month");
  });

  test("every-minute is outside the fallback's envelope and says so with both numbers", () => {
    const result = calendarIntervals("* * * * *");
    expect("error" in result && result.error).toContain("1440");
    expect("error" in result && result.error).toContain(String(MAX_CALENDAR_INTERVALS));
  });

  test("the cap is 366 dicts per plist", () => {
    expect(MAX_CALENDAR_INTERVALS).toBe(366);
  });

  test("a schedule at the cap is accepted", () => {
    const result = calendarIntervals("0 * * * *");
    expect("intervals" in result && result.intervals).toHaveLength(24);
  });

  test("a schedule that is not five fields is an error, not a guess", () => {
    expect("error" in calendarIntervals("0 3 * *")).toBe(true);
    expect("error" in calendarIntervals("")).toBe(true);
  });

  test("a non-numeric or out-of-range field is an error", () => {
    expect("error" in calendarIntervals("0 3 * * MON")).toBe(true);
    expect("error" in calendarIntervals("60 3 * * *")).toBe(true);
    expect("error" in calendarIntervals("0 24 * * *")).toBe(true);
    expect("error" in calendarIntervals("*/0 3 * * *")).toBe(true);
  });
});

describe("the plist can fire, and cannot be broken by its own interpolation", () => {
  const intervals = [{ Minute: 0, Hour: 3 }];

  test("it carries a scheduling key — without one the job never fires", () => {
    const xml = plistFor("com.ai-badger.pi-cron.x", "echo hi", intervals);
    expect(xml).toContain("<key>StartCalendarInterval</key>");
    expect(xml).toContain("<key>Minute</key>");
    expect(xml).toContain("<integer>3</integer>");
  });

  test("RunAtLoad and KeepAlive stay false so the scheduling key is the only fire mechanism", () => {
    const xml = plistFor("com.ai-badger.pi-cron.x", "echo hi", intervals);
    expect(xml).toContain("<key>RunAtLoad</key>\n  <false/>");
    expect(xml).toContain("<key>KeepAlive</key>\n  <false/>");
    expect(xml).not.toContain("<true/>");
  });

  test("every interpolated value is XML-escaped", () => {
    const xml = plistFor("com.ai-badger.pi-cron.x", 'echo "a" && b < c', intervals);
    expect(xml).toContain("echo &quot;a&quot; &amp;&amp; b &lt; c");
    expect(xml).not.toContain('echo "a" && b < c');
  });

  test("xmlEscape covers the five XML entities", () => {
    expect(xmlEscape(`&<>"'`)).toBe("&amp;&lt;&gt;&quot;&apos;");
  });
});

describe("the stale-job prune knows both prefixes", () => {
  test("an orphan under either prefix is pruned", () => {
    const existing = [
      `${LAUNCHD_LABEL_PREFIX}gone`,
      `${BUN_LABEL_PREFIX}also-gone`,
      `${LAUNCHD_LABEL_PREFIX}kept`,
      `${BUN_LABEL_PREFIX}kept`,
      "com.apple.something",
    ];
    expect(staleLabels(existing, ["kept"]).sort()).toEqual(
      [`${BUN_LABEL_PREFIX}also-gone`, `${LAUNCHD_LABEL_PREFIX}gone`].sort(),
    );
  });

  test("a prune that knew only one prefix would leave the other orphaned forever", () => {
    expect(staleLabels([`${BUN_LABEL_PREFIX}gone`], [])).toEqual([`${BUN_LABEL_PREFIX}gone`]);
    expect(staleLabels([`${LAUNCHD_LABEL_PREFIX}gone`], [])).toEqual([
      `${LAUNCHD_LABEL_PREFIX}gone`,
    ]);
  });

  test("labels belonging to anyone else are never touched", () => {
    expect(staleLabels(["com.apple.something", "homebrew.mxcl.foo"], [])).toEqual([]);
  });
});

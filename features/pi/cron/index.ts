/**
 * ai-badger cron for pi: registers the jobs declared in ~/.config/ai-badger/cron.json.
 *
 * Two rungs, in this order:
 *   1. running under bun -> in-process `Bun.cron`;
 *   2. otherwise -> a self-managed launchd agent per job.
 * pi's bin is `#!/usr/bin/env node`, so rung 2 is the one that fires today; rung 1 exists for
 * the day pi runs under bun and is written so it cannot rot in the meantime.
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { CRON_CONFIG_PATH, loadCronConfig } from "./config.ts";

// ---------------------------------------------------------------------------
// Pure cron-config logic: which jobs are schedulable, how a five-field cron schedule becomes
// launchd StartCalendarInterval dicts, and which launchd labels are ours but no longer wanted.
// Exported so every branch is unit-testable without touching launchd.
// ---------------------------------------------------------------------------

export interface CronJob {
  title: string;
  schedule: string;
  command: string;
  noAgent?: boolean;
}

export type CalendarInterval = {
  Minute: number;
  Hour: number;
  Day?: number;
  Month?: number;
  Weekday?: number;
};

export type IntervalResult = { intervals: CalendarInterval[] } | { error: string };

/** One plist's dict budget. `* * * * *` needs 1440, which is why sub-hourly work is refused. */
export const MAX_CALENDAR_INTERVALS = 366;

export const LAUNCHD_LABEL_PREFIX = "com.ai-badger.pi-cron.";
/** Bun's own launchd label for a `Bun.cron` job registered under the ai-badger title prefix. */
export const BUN_LABEL_PREFIX = "bun.cron.ai-badger-cron-";

const TITLE = /^[A-Za-z0-9_-]+$/;

/** Jobs to schedule: `noAgent` defaults to true, so only an explicit `false` opts out. */
export function schedulableJobs(jobs: CronJob[]): CronJob[] {
  return jobs.filter((job) => job.noAgent !== false);
}

/** The title if it is safe as a launchd label component, otherwise null — never a silent strip. */
export function sanitizeTitle(title: string): string | null {
  return TITLE.test(title) ? title : null;
}

/** Every value a single cron field covers, or null when the field is unusable. */
function expandField(spec: string, min: number, max: number): number[] | null {
  const values = new Set<number>();
  for (const part of spec.split(",")) {
    const [range, stepText] = part.split("/");
    if (range === undefined || range === "") return null;
    let step = 1;
    if (stepText !== undefined) {
      step = Number(stepText);
      if (!Number.isInteger(step) || step < 1) return null;
    }
    let from: number;
    let to: number;
    if (range === "*") {
      from = min;
      to = max;
    } else if (range.includes("-")) {
      const [a, b] = range.split("-");
      from = Number(a);
      to = Number(b);
    } else {
      from = Number(range);
      to = stepText === undefined ? from : max;
    }
    if (!Number.isInteger(from) || !Number.isInteger(to)) return null;
    if (from < min || to > max || from > to) return null;
    for (let value = from; value <= to; value += step) values.add(value);
  }
  return values.size ? [...values].sort((a, b) => a - b) : null;
}

/**
 * A five-field cron schedule as launchd `StartCalendarInterval` dicts, or the reason it cannot be.
 * A `*` day, month or weekday is omitted rather than expanded — omission is launchd's own "every".
 */
export function calendarIntervals(schedule: string): IntervalResult {
  const fields = schedule.trim().split(/\s+/);
  if (fields.length !== 5 || fields.some((f) => !f)) {
    return { error: `"${schedule}" is not a five-field cron schedule` };
  }
  const [minuteSpec, hourSpec, daySpec, monthSpec, weekdaySpec] = fields as [
    string,
    string,
    string,
    string,
    string,
  ];

  if (daySpec !== "*" && weekdaySpec !== "*") {
    return {
      error:
        `"${schedule}" restricts both day-of-month and weekday; cron treats that as OR and ` +
        "launchd as AND, so the two cannot be translated without changing when the job fires",
    };
  }

  const minutes = expandField(minuteSpec, 0, 59);
  const hours = expandField(hourSpec, 0, 23);
  const days = daySpec === "*" ? null : expandField(daySpec, 1, 31);
  const months = monthSpec === "*" ? null : expandField(monthSpec, 1, 12);
  const weekdays = weekdaySpec === "*" ? null : expandField(weekdaySpec, 0, 7);
  if (!minutes || !hours) return { error: `"${schedule}" has an unreadable minute or hour field` };
  if (daySpec !== "*" && !days) return { error: `"${schedule}" has an unreadable day field` };
  if (monthSpec !== "*" && !months) return { error: `"${schedule}" has an unreadable month field` };
  if (weekdaySpec !== "*" && !weekdays) {
    return { error: `"${schedule}" has an unreadable weekday field` };
  }

  const count =
    minutes.length * hours.length * (days?.length ?? 1) * (months?.length ?? 1) *
    (weekdays?.length ?? 1);
  if (count > MAX_CALENDAR_INTERVALS) {
    return {
      error:
        `"${schedule}" expands to ${count} StartCalendarInterval dicts and the cap is ` +
        `${MAX_CALENDAR_INTERVALS}; schedules this fine-grained are outside the launchd ` +
        "fallback's envelope",
    };
  }

  const intervals: CalendarInterval[] = [];
  for (const month of months ?? [undefined]) {
    for (const day of days ?? [undefined]) {
      for (const weekday of weekdays ?? [undefined]) {
        for (const hour of hours) {
          for (const minute of minutes) {
            const interval: CalendarInterval = { Minute: minute, Hour: hour };
            if (day !== undefined) interval.Day = day;
            if (month !== undefined) interval.Month = month;
            if (weekday !== undefined) interval.Weekday = weekday;
            intervals.push(interval);
          }
        }
      }
    }
  }
  return { intervals };
}

export function xmlEscape(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function intervalXml(interval: CalendarInterval): string {
  const entries = Object.entries(interval)
    .filter(([, value]) => value !== undefined)
    .map(([key, value]) => `      <key>${key}</key>\n      <integer>${value}</integer>`)
    .join("\n");
  return `    <dict>\n${entries}\n    </dict>`;
}

/** A launchd agent that fires only on its calendar intervals. Every value is XML-escaped. */
export function plistFor(
  label: string,
  command: string,
  intervals: CalendarInterval[],
): string {
  const safeLabel = xmlEscape(label);
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${safeLabel}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>${xmlEscape(command)}</string>
  </array>
  <key>RunAtLoad</key>
  <false/>
  <key>KeepAlive</key>
  <false/>
  <key>StartCalendarInterval</key>
  <array>
${intervals.map(intervalXml).join("\n")}
  </array>
  <key>StandardOutPath</key>
  <string>/tmp/${safeLabel}.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/${safeLabel}.err</string>
</dict>
</plist>
`;
}

/**
 * Our labels that no current job claims — scanned under both prefixes, because a prune that
 * knows only one leaves the other's agents firing forever.
 */
export function staleLabels(existing: string[], currentTitles: string[]): string[] {
  const current = new Set(currentTitles);
  return existing.filter((label) => {
    for (const prefix of [LAUNCHD_LABEL_PREFIX, BUN_LABEL_PREFIX]) {
      if (label.startsWith(prefix)) return !current.has(label.slice(prefix.length));
    }
    return false;
  });
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

const LAUNCH_AGENTS_DIR = join(homedir(), "Library", "LaunchAgents");
const BUN_TITLE_PREFIX = "ai-badger-cron-";

/** True only when the process really is bun. `bun` on PATH says nothing about this runtime. */
function underBun(): boolean {
  return typeof (globalThis as { Bun?: unknown }).Bun !== "undefined";
}

function launchctl(args: string[]): boolean {
  try {
    execFileSync("/bin/launchctl", args, { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

function plistPath(label: string): string {
  return join(LAUNCH_AGENTS_DIR, `${label}.plist`);
}

/**
 * Unload the label before loading it again. Without this an edited schedule keeps the old
 * definition firing, because launchd holds the definition it was given, not the file.
 */
function reload(label: string, path: string): void {
  const domain = `gui/${process.getuid?.() ?? 0}`;
  if (!launchctl(["bootout", `${domain}/${label}`])) launchctl(["unload", path]);
  if (!launchctl(["bootstrap", domain, path])) launchctl(["load", path]);
}

function registerWithBun(job: CronJob, title: string): void {
  // ESM has no __dirname; import.meta.url is how a sibling file is addressed here.
  const script = fileURLToPath(new URL("run-job.ts", import.meta.url));
  const bun = (globalThis as { Bun?: { cron: (s: string, c: string, t: string) => void } }).Bun;
  bun?.cron(script, job.schedule, `${BUN_TITLE_PREFIX}${title}`);
}

/** Write and load one launchd agent, or return why the job was skipped. */
function registerWithLaunchd(job: CronJob, title: string): string | null {
  const schedule = calendarIntervals(job.schedule);
  if ("error" in schedule) return `cron job "${title}" skipped: ${schedule.error}`;

  const label = `${LAUNCHD_LABEL_PREFIX}${title}`;
  const path = plistPath(label);
  try {
    mkdirSync(LAUNCH_AGENTS_DIR, { recursive: true });
    writeFileSync(path, plistFor(label, job.command, schedule.intervals), "utf-8");
  } catch (error) {
    return `cron job "${title}" skipped: ${path} could not be written (${String(error)})`;
  }
  reload(label, path);
  return null;
}

/** Remove our launchd agents that no current job claims, under both prefixes. */
function pruneStale(currentTitles: string[]): string[] {
  let entries: string[];
  try {
    entries = readdirSync(LAUNCH_AGENTS_DIR);
  } catch {
    return [];
  }
  const labels = entries
    .filter((name) => name.endsWith(".plist"))
    .map((name) => name.slice(0, -".plist".length))
    .filter(
      (label) => label.startsWith(LAUNCHD_LABEL_PREFIX) || label.startsWith(BUN_LABEL_PREFIX),
    );

  const removed: string[] = [];
  for (const label of staleLabels(labels, currentTitles)) {
    const path = plistPath(label);
    const domain = `gui/${process.getuid?.() ?? 0}`;
    if (!launchctl(["bootout", `${domain}/${label}`])) launchctl(["unload", path]);
    try {
      if (existsSync(path)) unlinkSync(path);
      removed.push(label);
    } catch {
      // the agent is unloaded; a plist we cannot delete is inert
    }
  }
  return removed;
}

export default async function (pi: ExtensionAPI) {
  const { jobs } = loadCronConfig();
  const notices: string[] = [];
  const registered: string[] = [];
  const bun = underBun();

  for (const job of schedulableJobs(jobs)) {
    const title = sanitizeTitle(job.title);
    if (title === null) {
      notices.push(
        `cron job "${job.title}" skipped: a title must match [A-Za-z0-9_-] to be a launchd label`,
      );
      continue;
    }
    if (bun) {
      registerWithBun(job, title);
      registered.push(title);
      continue;
    }
    const problem = registerWithLaunchd(job, title);
    if (problem) notices.push(problem);
    else registered.push(title);
  }

  const pruned = pruneStale(registered);
  if (pruned.length) notices.push(`cron: pruned stale job(s) ${pruned.join(", ")}`);

  pi.on("session_start", async (_event, ctx) => {
    for (const notice of notices) ctx.ui.notify(`ai-badger ${notice}`, "warning");
    ctx.ui.setStatus(
      "cron",
      jobs.length === 0
        ? `Cron: no jobs in ${CRON_CONFIG_PATH}`
        : `Cron: ${registered.length}/${schedulableJobs(jobs).length} job(s) registered`,
    );
  });

  pi.registerCommand("cron-status", {
    description: "Show ai-badger cron jobs and how they are registered",
    handler: async (_args, ctx) => {
      const current = loadCronConfig().jobs;
      const lines = current.map((job) => {
        const state = job.noAgent === false ? "opted out" : "schedulable";
        return `  ${job.title} [${state}] ${job.schedule} -> ${job.command}`;
      });
      const rung = bun ? "in-process Bun.cron" : "launchd agents";
      ctx.ui.notify(
        [`ai-badger cron (${rung}), from ${CRON_CONFIG_PATH}:`, ...lines, ...notices].join("\n"),
        notices.length ? "warning" : "info",
      );
    },
  });
}

/** Where ai-badger's cron jobs are declared, and how to read them. */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { CronJob } from "./index.ts";

export const CRON_CONFIG_PATH = join(homedir(), ".config", "ai-badger", "cron.json");

/** The declared jobs, read fresh from disk. An unreadable or malformed config yields none. */
export function loadCronConfig(path: string = CRON_CONFIG_PATH): { jobs: CronJob[] } {
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, "utf-8"));
    if (parsed && typeof parsed === "object" && Array.isArray((parsed as { jobs?: unknown }).jobs)) {
      return { jobs: (parsed as { jobs: CronJob[] }).jobs };
    }
  } catch {
    // missing or invalid config — no jobs
  }
  return { jobs: [] };
}

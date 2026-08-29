/**
 * The script a `Bun.cron` job fires. Bun requires `default.scheduled(controller)`; a
 * top-level-only script fails with "Module does not export default.scheduled()".
 *
 * The config is read here, at fire time, never captured when the job was registered — an
 * edited cron.json must take effect without re-registering. Only the bun rung uses this file;
 * the launchd fallback puts the job's command in the plist and runs it directly.
 */

import { spawnSync } from "node:child_process";
import { loadCronConfig } from "./config.ts";
import { schedulableJobs } from "./index.ts";

export interface ScheduledController {
  /** The cron expression the fired job was registered with, when bun provides it. */
  cron?: string;
  scheduledTime?: number;
}

/** The jobs this fire is for: the one bun names by title, else every job on that schedule. */
export function jobsToRun(
  config: { jobs: import("./index.ts").CronJob[] },
  controller: ScheduledController,
  title: string | undefined,
): import("./index.ts").CronJob[] {
  const schedulable = schedulableJobs(config.jobs);
  if (title) return schedulable.filter((job) => job.title === title);
  if (controller.cron) return schedulable.filter((job) => job.schedule === controller.cron);
  return [];
}

export default {
  async scheduled(controller: ScheduledController): Promise<void> {
    const title = process.env.AI_BADGER_CRON_TITLE;
    for (const job of jobsToRun(loadCronConfig(), controller, title)) {
      const result = spawnSync("/bin/sh", ["-c", job.command], { encoding: "utf-8" });
      if (result.status !== 0) {
        console.error(`ai-badger cron "${job.title}" exited ${result.status}: ${result.stderr}`);
      }
    }
  },
};

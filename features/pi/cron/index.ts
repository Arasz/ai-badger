import { existsSync } from "fs";
import { execSync } from "child_process";
import { homedir } from "os";
import { join } from "path";
import { readFileSync, writeFileSync, mkdirSync } from "fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const CRON_CONFIG_PATH = join(homedir(), ".config", "ai-badger", "cron.json");
const CRON_TITLE_PREFIX = "ai-badger-cron";
const HAS_BUN = (() => {
  try {
    execSync("which bun", { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
})();

interface CronJob {
  title: string;
  schedule: string;
  command: string;
  noAgent: boolean;
}

interface CronConfig {
  jobs: CronJob[];
}

function loadCronConfig(): CronConfig {
  try {
    if (existsSync(CRON_CONFIG_PATH)) {
      const content = readFileSync(CRON_CONFIG_PATH, "utf-8");
      return JSON.parse(content);
    }
  } catch {
    // config file missing or invalid — start empty
  }
  return { jobs: [] };
}

function registerWithBun(job: CronJob): void {
  // Bun.cron(path, schedule, title) — OS-level, uses launchd on macOS
  const scriptPath = join(__dirname, "run-job.ts");
  Bun.cron(scriptPath, job.schedule, `${CRON_TITLE_PREFIX}-${job.title}`);
}

function registerWithLaunchd(job: CronJob): void {
  // macOS launchd plist fallback
  const label = `com.ai-badger.pi-cron.${job.title}`;
  const plistPath = join(homedir(), "Library", "LaunchAgents", `${label}.plist`);

  const plist = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>${job.command}</string>
  </array>
  <key>RunAtLoad</key>
  <false/>
  <key>KeepAlive</key>
  <false/>
  <key>StandardOutPath</key>
  <string>/tmp/${label}.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/${label}.err</string>
</dict>
</plist>`;

  writeFileSync(plistPath, plist, "utf-8");
  try {
    execSync(`launchctl load "${plistPath}"`, { stdio: "ignore" });
  } catch {
    // launchctl may fail if already loaded — that's fine
  }
}

function registerJob(job: CronJob): void {
  if (HAS_BUN) {
    registerWithBun(job);
  } else {
    registerWithLaunchd(job);
  }
}

export default async function (pi: ExtensionAPI) {
  const config = loadCronConfig();

  if (config.jobs.length === 0) {
    pi.on("session_start", async (_event, ctx) => {
      ctx.ui.notify("Cron: No jobs configured in ~/.config/ai-badger/cron.json", "info");
    });
    return;
  }

  for (const job of config.jobs) {
    if (job.noAgent) {
      registerJob(job);
    }
  }

  pi.on("session_start", async (_event, ctx) => {
    const jobCount = config.jobs.filter((j) => j.noAgent).length;
    ctx.ui.setStatus("cron", `Cron: ${jobCount} no-agent jobs`);
  });

  pi.registerCommand("cron-status", {
    description: "Show registered cron jobs",
    handler: async (_args, ctx) => {
      const lines = config.jobs.map(
        (j) => `  ${j.noAgent ? "(no-agent)" : ""} ${j.title}: ${j.schedule} → ${j.command}`,
      );
      ctx.ui.notify(`Cron Jobs:\n${lines.join("\n")}`, "info");
    },
  });
}
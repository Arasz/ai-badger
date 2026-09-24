/**
 * Bus mail the adapter consumes mid-run must be durable: in the persisted session, emitted
 * as a message (the TUI renders from message events), and present on every later LLM call
 * of the run. Driven through pi's real AgentSession, extension runner and agent loop; only
 * the LLM (pi-ai's faux stream) and the bus I/O (BusDeps) are fakes, and every path lives
 * under a tmp dir.
 */

import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  createAgentSession,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import {
  fauxAssistantMessage,
  fauxProvider,
  fauxToolCall,
  type Context,
} from "@earendil-works/pi-ai";
import adapter from "../adjustments/adapter/index.ts";
import type { BusDeps } from "../adjustments/adapter/index.ts";
import type { DeliveryOutcome } from "../adjustments/adapter/hook-bridge.ts";

const MAIL = "MAIL-FROM-PEER";

let root: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "aib-pi-mail-durable-"));
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

/** A wired project (the delivery script exists; it is never run — deliver is injected)
 * plus a file for the faux model's read tool calls. */
function makeProject(): { cwd: string; agentDir: string } {
  const cwd = join(root, "project");
  const agentDir = join(root, "agent");
  mkdirSync(join(cwd, ".ai-badger", "hooks"), { recursive: true });
  mkdirSync(agentDir, { recursive: true });
  writeFileSync(join(cwd, ".ai-badger", "hooks", "message_delivery_hook.py"), "# fixture\n");
  writeFileSync(join(cwd, "notes.txt"), "a file to read\n");
  return { cwd, agentDir };
}

function mailCount(context: Context): number {
  return JSON.stringify(context.messages).split(MAIL).length - 1;
}

test("mail consumed mid-run is persisted, emitted, and on every later LLM call exactly once", async () => {
  const { cwd, agentDir } = makeProject();

  // The store, reduced to what the adapter observes: one mail lands while LLM call 1 is in
  // flight, and the exactly-once txn hands it out to the first delivery after that.
  let mailArrived = false;
  let consumed = 0;
  const busDeps: BusDeps = {
    setInterval: () => ({}),
    clearInterval: () => {},
    probeBus: async () => ({
      kind: "ok",
      fingerprint: { maxId: mailArrived ? 2 : 1, count: mailArrived ? 2 : 1, dev: 1, ino: 2 },
    }),
    deliver: async (): Promise<DeliveryOutcome> => {
      if (!mailArrived || consumed > 0) return { kind: "empty" };
      consumed += 1;
      return { kind: "context", content: MAIL, bus: { addressed: 1, broadcast: 0 } };
    },
  };

  const requests: Context[] = [];
  const faux = fauxProvider();
  faux.setResponses([
    (context) => {
      requests.push(context);
      mailArrived = true;
      return fauxAssistantMessage(fauxToolCall("read", { path: "notes.txt" }), { stopReason: "toolUse" });
    },
    (context) => {
      requests.push(context);
      return fauxAssistantMessage(fauxToolCall("read", { path: "notes.txt" }), { stopReason: "toolUse" });
    },
    (context) => {
      requests.push(context);
      return fauxAssistantMessage("done");
    },
  ]);

  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false } });
  const resourceLoader = new DefaultResourceLoader({
    cwd,
    agentDir,
    settingsManager,
    extensionFactories: [(pi) => adapter(pi, busDeps)],
  });
  await resourceLoader.reload();
  const sessionManager = SessionManager.inMemory(cwd);
  const modelRuntime = await ModelRuntime.create({
    authPath: join(agentDir, "auth.json"),
    modelsPath: join(agentDir, "models.json"),
    allowModelNetwork: false,
    refreshOnCreate: false,
  });
  modelRuntime.registerNativeProvider(faux.provider);
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    modelRuntime,
    model: faux.getModel(),
    tools: ["read"],
    resourceLoader,
    sessionManager,
    settingsManager,
  });
  await session.bindExtensions({});

  const emitted: string[] = [];
  session.subscribe((event) => {
    if (event.type === "message_end" && event.message.role === "custom") {
      emitted.push(JSON.stringify(event.message.content));
    }
  });

  await session.prompt("hi");
  await session.agent.waitForIdle();

  const persisted = sessionManager
    .getEntries()
    .filter((entry) => entry.type === "custom_message" && JSON.stringify(entry).includes(MAIL));
  expect({
    consumed,
    mailPerRequest: requests.map(mailCount),
    emitted: emitted.filter((content) => content.includes(MAIL)).length,
    persisted: persisted.length,
  }).toEqual({ consumed: 1, mailPerRequest: [0, 1, 1], emitted: 1, persisted: 1 });

  session.dispose();
});

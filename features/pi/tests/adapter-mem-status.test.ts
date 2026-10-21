/**
 * The memory-first gate's footer status in pi: `[mem <searched> <pct>%]`.
 *
 * The gate answers a repo text search with the memory result and keeps the raw grep output
 * alive for a while; the `get-raw-text-search` skill fetches that output. The adapter sees
 * both halves — the gate's answer arrives as `additionalContext`, the fetch arrives as a
 * bash call — so it can report whether the capture was worth its cost.
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import adapter from "../adjustments/adapter/index.ts";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;

/** Install the default export against a fake pi. */
async function loadAdapter(): Promise<{ toolCall: Handler; toolResult: Handler; sessionStart: Handler }> {
	const on = new Map<string, Handler>();
	await adapter({
		on: (event: string, handler: Handler) => on.set(event, handler),
		registerCommand: () => undefined,
	} as never);
	return {
		toolCall: on.get("tool_call")!,
		toolResult: on.get("tool_result")!,
		sessionStart: on.get("session_start")!,
	};
}

/** A pi extension context whose footer status is recorded. */
function fakeCtx(cwd: string): {
	cwd: string;
	hasUI: boolean;
	mode: string;
	ui: { notify: () => void; setStatus: (key: string, text: string | undefined) => void };
	statuses: Array<[string, string | undefined]>;
} {
	const statuses: Array<[string, string | undefined]> = [];
	return {
		cwd,
		hasUI: false,
		mode: "tui",
		ui: {
			notify: () => undefined,
			setStatus: (key: string, text: string | undefined) => statuses.push([key, text]),
		},
		statuses,
	};
}

/** The handle the fake gate captured, and the command that fetches it back. */
const CAPTURED_HASH = "a".repeat(64);
/** The gate's searched patterns: one the gate captured raw output for, one it did not. */
const DEFAULT_ENTRIES = [
	{ pattern: "foo", rawResultHash: CAPTURED_HASH },
	{ pattern: "bar" },
];
const FETCH_COMMAND =
	`python3 .ai-badger/skills/get-raw-text-search/scripts/get_raw_text_search.py --pattern-hash ${CAPTURED_HASH}`;

/** A retrieval answer, as the script prints it. */
function retrieval(status: string, hash = CAPTURED_HASH): Array<{ type: string; text: string }> {
	return [{ type: "text", text: JSON.stringify({ status, hash }) }];
}

describe("the memory gate's footer status in pi", () => {
	let dir: string;

	beforeEach(() => {
		dir = mkdtempSync(join(tmpdir(), "aib-mem-status-"));
	});

	afterEach(() => {
		rmSync(dir, { recursive: true, force: true });
	});

	/**
	 * Write a gate that answers every bash call except a raw-result fetch, with the
	 * gate's context: the searched patterns, and the raw handle of the captured ones.
	 * `deny` makes it deny the fetch instead — the retrieval never runs.
	 */
	function writeGate(deny = false, entries = DEFAULT_ENTRIES): void {
		const hooksDir = join(dir, ".ai-badger", "hooks");
		mkdirSync(hooksDir, { recursive: true });
		const context = [
			'Memory context (ai-raccoon memory_search, snippets — query: "foo"):',
			"  (no memory hits)",
			"",
			JSON.stringify({ textSearchInput: entries }),
		].join("\n");
		const answer = JSON.stringify({
			hookSpecificOutput: { hookEventName: "PreToolUse", additionalContext: context },
		});
		const denyAnswer = JSON.stringify({
			hookSpecificOutput: {
				hookEventName: "PreToolUse",
				permissionDecision: "deny",
				permissionDecisionReason: "guarded",
			},
		});
		const script = join(dir, "gate.sh");
		writeFileSync(
			script,
			[
				"#!/bin/sh",
				"payload=$(cat)",
				'case "$payload" in',
				`  *get_raw_text_search*) printf '%s' '${deny ? denyAnswer : ""}'; exit 0 ;;`,
				"esac",
				`printf '%s' '${answer}'`,
			].join("\n"),
		);
		chmodSync(script, 0o755);
		writeFileSync(
			join(hooksDir, "hooks.json"),
			JSON.stringify({
				hooks: {
					PreToolUse: [{ matcher: "Bash", hooks: [{ type: "command", command: script }] }],
				},
			}),
		);
	}

	/** One gated grep: the gate answers it, and the call runs. */
	async function capture(
		toolCall: Handler,
		toolResult: Handler,
		ctx: ReturnType<typeof fakeCtx>,
	): Promise<void> {
		await toolCall(
			{ toolName: "bash", toolCallId: "call-1", input: { command: "grep -rn foo src/" } },
			ctx,
		);
		await toolResult(
			{
				toolName: "bash",
				toolCallId: "call-1",
				input: { command: "grep -rn foo src/" },
				content: [{ type: "text", text: "src/a.ts:1:foo" }],
			},
			ctx,
		);
	}

	test("a captured search shows up in the footer", async () => {
		writeGate();
		const { toolCall, toolResult } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await capture(toolCall, toolResult, ctx);

		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 2 0%]"]);
	});

	test("a search the gate could not capture still shows up in the footer", async () => {
		writeGate(false, [{ pattern: "bar" }]);
		const { toolCall, toolResult } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await capture(toolCall, toolResult, ctx);

		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 1 0%]"]);
	});

	test("a raw-result fetch is counted, and the footer follows", async () => {
		writeGate();
		const { toolCall, toolResult } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await capture(toolCall, toolResult, ctx);
		await toolCall(
			{ toolName: "bash", toolCallId: "call-2", input: { command: FETCH_COMMAND } },
			ctx,
		);
		await toolResult(
			{
				toolName: "bash",
				toolCallId: "call-2",
				input: { command: FETCH_COMMAND },
				content: retrieval("ready"),
			},
			ctx,
		);

		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 2 100%]"]);
	});

	test("a denied fetch is not counted — the retrieval never ran", async () => {
		writeGate(true);
		const { toolCall, toolResult } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await capture(toolCall, toolResult, ctx);
		const blocked = await toolCall(
			{ toolName: "bash", toolCallId: "call-2", input: { command: FETCH_COMMAND } },
			ctx,
		);

		expect(blocked).toMatchObject({ block: true });
		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 2 0%]"]);
	});

	test("a pending retrieval is not a fetch yet — the skill retries it", async () => {
		writeGate();
		const { toolCall, toolResult } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await capture(toolCall, toolResult, ctx);
		await toolCall(
			{ toolName: "bash", toolCallId: "call-2", input: { command: FETCH_COMMAND } },
			ctx,
		);
		await toolResult(
			{
				toolName: "bash",
				toolCallId: "call-2",
				input: { command: FETCH_COMMAND },
				content: retrieval("pending"),
			},
			ctx,
		);

		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 2 0%]"]);
	});

	test("reading one handle twice fetched one result", async () => {
		writeGate();
		const { toolCall, toolResult } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await capture(toolCall, toolResult, ctx);
		for (const id of ["call-2", "call-3"]) {
			await toolCall(
				{ toolName: "bash", toolCallId: id, input: { command: FETCH_COMMAND } },
				ctx,
			);
			await toolResult(
				{
					toolName: "bash",
					toolCallId: id,
					input: { command: FETCH_COMMAND },
					content: retrieval("ready"),
				},
				ctx,
			);
		}

		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 2 100%]"]);
	});

	test("a retrieval the gate did not capture is not part of the ratio", async () => {
		writeGate();
		const { toolCall, toolResult } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await capture(toolCall, toolResult, ctx);
		await toolCall(
			{ toolName: "bash", toolCallId: "call-2", input: { command: FETCH_COMMAND } },
			ctx,
		);
		await toolResult(
			{
				toolName: "bash",
				toolCallId: "call-2",
				input: { command: FETCH_COMMAND },
				content: retrieval("ready", "b".repeat(64)),
			},
			ctx,
		);

		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 2 0%]"]);
	});

	test("a new session starts the counters over", async () => {
		writeGate();
		const { toolCall, toolResult, sessionStart } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await capture(toolCall, toolResult, ctx);
		await toolCall(
			{ toolName: "bash", toolCallId: "call-2", input: { command: FETCH_COMMAND } },
			ctx,
		);
		await toolResult(
			{
				toolName: "bash",
				toolCallId: "call-2",
				input: { command: FETCH_COMMAND },
				content: retrieval("ready"),
			},
			ctx,
		);
		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 2 100%]"]);

		// /new, /resume, /fork and /clone re-fire session_start on the same adapter.
		await sessionStart({}, ctx);
		expect(ctx.statuses.at(-1)).toEqual(["mem", undefined]);

		await capture(toolCall, toolResult, ctx);
		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 2 0%]"]);
	});

	test("a gate that searched nothing shows no status at all", async () => {
		const hooksDir = join(dir, ".ai-badger", "hooks");
		mkdirSync(hooksDir, { recursive: true });
		writeFileSync(
			join(hooksDir, "hooks.json"),
			JSON.stringify({
				hooks: { PreToolUse: [{ matcher: "Bash", hooks: [{ type: "command", command: "true" }] }] },
			}),
		);
		const { toolCall, toolResult } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await capture(toolCall, toolResult, ctx);

		expect(ctx.statuses.at(-1)).toEqual(["mem", undefined]);
	});
});

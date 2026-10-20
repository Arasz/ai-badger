/**
 * The memory-first gate's footer status in pi: `[mem <captured> <fetched>/<captured>%]`.
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
async function loadAdapter(): Promise<{ toolCall: Handler }> {
	const on = new Map<string, Handler>();
	await adapter({
		on: (event: string, handler: Handler) => on.set(event, handler),
		registerCommand: () => undefined,
	} as never);
	return { toolCall: on.get("tool_call")! };
}

/** A pi extension context whose footer status is recorded. */
function fakeCtx(cwd: string): {
	cwd: string;
	hasUI: boolean;
	ui: { notify: () => void; setStatus: (key: string, text: string | undefined) => void };
	statuses: Array<[string, string | undefined]>;
} {
	const statuses: Array<[string, string | undefined]> = [];
	return {
		cwd,
		hasUI: false,
		ui: {
			notify: () => undefined,
			setStatus: (key: string, text: string | undefined) => statuses.push([key, text]),
		},
		statuses,
	};
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
	 * gate's context: one captured pattern, and one the gate could not capture.
	 */
	function writeGate(): void {
		const hooksDir = join(dir, ".ai-badger", "hooks");
		mkdirSync(hooksDir, { recursive: true });
		const context = [
			'Memory context (ai-raccoon memory_search, snippets — query: "foo"):',
			"  (no memory hits)",
			"",
			JSON.stringify({
				textSearchInput: [
					{ pattern: "foo", rawResultHash: "a".repeat(64) },
					{ pattern: "bar" },
				],
			}),
		].join("\n");
		const script = join(dir, "gate.sh");
		writeFileSync(
			script,
			[
				"#!/bin/sh",
				"payload=$(cat)",
				'case "$payload" in',
				"  *get_raw_text_search*) exit 0 ;;",
				"esac",
				`printf '%s' '${JSON.stringify({
					hookSpecificOutput: { hookEventName: "PreToolUse", additionalContext: context },
				})}'`,
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

	test("a captured search shows up in the footer", async () => {
		writeGate();
		const { toolCall } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await toolCall(
			{ toolName: "bash", toolCallId: "call-1", input: { command: "grep -rn foo src/" } },
			ctx,
		);

		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 1 0/1%]"]);
	});

	test("a raw-result fetch is counted, and the footer follows", async () => {
		writeGate();
		const { toolCall } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await toolCall(
			{ toolName: "bash", toolCallId: "call-1", input: { command: "grep -rn foo src/" } },
			ctx,
		);
		await toolCall(
			{
				toolName: "bash",
				toolCallId: "call-2",
				input: {
					command:
						"python3 .ai-badger/skills/get-raw-text-search/scripts/get_raw_text_search.py --pattern-hash abc",
				},
			},
			ctx,
		);

		expect(ctx.statuses.at(-1)).toEqual(["mem", "[mem 1 1/1%]"]);
	});

	test("a gate that captured nothing shows no status at all", async () => {
		const hooksDir = join(dir, ".ai-badger", "hooks");
		mkdirSync(hooksDir, { recursive: true });
		writeFileSync(
			join(hooksDir, "hooks.json"),
			JSON.stringify({
				hooks: { PreToolUse: [{ matcher: "Bash", hooks: [{ type: "command", command: "true" }] }] },
			}),
		);
		const { toolCall } = await loadAdapter();
		const ctx = fakeCtx(dir);

		await toolCall(
			{ toolName: "bash", toolCallId: "call-1", input: { command: "grep -rn foo src/" } },
			ctx,
		);

		expect(ctx.statuses.at(-1)).toEqual(["mem", undefined]);
	});
});

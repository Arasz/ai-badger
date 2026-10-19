/**
 * The memory-first gate is what redirects a text search to the ai-raccoon bank. In pi the
 * text-search tools are `grep` (file contents), `find` (file names) and greps inside bash.
 * `read` is a file view, not a search — it is deliberately NOT the gate's subject, and the
 * gate must not be widened to it by accident.
 *
 * Two halves make the redirect work in pi, and both are pinned here: the adapter's
 * tool-name mapping (pi `grep` → Claude's `Grep`) and the shipped gate's matcher, which
 * decides which tool calls reach the gate at all.
 */

import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { claudeToolInput, claudeToolName, commandsForTool, preToolUseCommands } from "../adjustments/adapter/hook-bridge.ts";

/** The project's shipped hooks.json — the framework writes it, the adapter reads it. */
const HOOKS_JSON = join(import.meta.dir, "..", "..", "..", ".ai-badger", "hooks", "hooks.json");

/** The PreToolUse entries of the shipped hooks.json. */
function shippedPreGates(): { matcher?: string; command: string }[] {
	const parsed = JSON.parse(readFileSync(HOOKS_JSON, "utf-8"));
	return preToolUseCommands(parsed);
}

/** The shipped gate that polices a text search: the memory-first hook. */
function memoryFirstGate(): { matcher?: string; command: string } {
	const gate = shippedPreGates().find((entry) => entry.command.includes("memory_first_gate"));
	expect(gate).toBeDefined();
	return gate!;
}

describe("pi's text-search tools are the memory-first gate's subject", () => {
	test("pi's grep, find and bash reach the shipped memory-first gate", () => {
		const gate = memoryFirstGate();

		for (const tool of ["grep", "find", "bash"]) {
			expect(commandsForTool([gate], claudeToolName(tool))).toHaveLength(1);
		}
	});

	test("pi's read does not: a file view is not a text search", () => {
		const gate = memoryFirstGate();

		expect(commandsForTool([gate], claudeToolName("read"))).toHaveLength(0);
	});

	test("the search pattern reaches the gate as the pattern, not as a blob of arguments", () => {
		expect(claudeToolInput("grep", { pattern: "TODO", path: "src", ignoreCase: true })).toEqual({
			pattern: "TODO",
			path: "src",
		});
		expect(claudeToolInput("find", { pattern: "*.ts", limit: 50 })).toEqual({ pattern: "*.ts" });
	});
});

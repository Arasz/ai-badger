/**
 * The memory-first gate's footer status: the pure counters behind `[mem <captured> <fetched>/<captured>%]`.
 *
 * The gate (ai-badger's memory-first gate) answers a repo text search with the memory result
 * instead of blocking it, and keeps the original grep/rg output alive for about two minutes.
 * The `get-raw-text-search` skill fetches that output. Two numbers say whether the capture is
 * worth its cost: how many searches were captured, and how many of those raw results the agent
 * actually fetched.
 */

import { describe, expect, test } from "bun:test";
import { countCaptured, formatMemStatus, isRawSearchFetch } from "../adjustments/adapter/mem-status.ts";

/** The gate's context: the memory block, then the JSON line it appends. */
function gateContext(entries: Array<{ pattern: string; rawResultHash?: string }>): string {
	const block = [
		'Memory context (ai-raccoon memory_search, snippets — query: "x"):',
		"- memories (snippets — to get full content use memory_get with the hash):",
		"  (no memory hits)",
	].join("\n");
	return `${block}\n\n${JSON.stringify({ textSearchInput: entries })}`;
}

describe("the memory gate's footer status", () => {
	test("the segment is bracketed, in the style the other pi extensions use", () => {
		expect(formatMemStatus({ captured: 12, fetched: 9 })).toBe("[mem 12 75%]");
		expect(formatMemStatus({ captured: 0, fetched: 0 })).toBe("[mem 0 0%]");
	});

	test("the fetched share is a percentage, rounded", () => {
		expect(formatMemStatus({ captured: 3, fetched: 1 })).toBe("[mem 3 33%]");
		expect(formatMemStatus({ captured: 4, fetched: 3 })).toBe("[mem 4 75%]");
		expect(formatMemStatus({ captured: 4, fetched: 4 })).toBe("[mem 4 100%]");
	});

	test("only a pattern with a captured raw output counts as captured", () => {
		const context = gateContext([
			{ pattern: "one", rawResultHash: "a".repeat(64) },
			{ pattern: "two" },
			{ pattern: "three", rawResultHash: "b".repeat(64) },
		]);
		expect(countCaptured([context])).toBe(2);
	});

	test("a context without a text-search record counts nothing", () => {
		expect(countCaptured(["just a memory block, no JSON tail"])).toBe(0);
		expect(countCaptured([])).toBe(0);
	});

	test("an unparseable tail counts nothing and never throws", () => {
		expect(countCaptured(["block\n\n{not json}"])).toBe(0);
		expect(countCaptured(["block\n\n[1,2,3]"])).toBe(0);
	});

	test("every context counts, and one context counts once", () => {
		const first = gateContext([{ pattern: "one", rawResultHash: "a".repeat(64) }]);
		const second = gateContext([{ pattern: "two", rawResultHash: "b".repeat(64) }]);
		expect(countCaptured([first, second])).toBe(2);
		expect(countCaptured([first, first])).toBe(2);
	});

	test("a raw-result fetch is the retrieval, never the gate's own capture worker", () => {
		expect(
			isRawSearchFetch(
				"python3 .ai-badger/skills/get-raw-text-search/scripts/get_raw_text_search.py --pattern-hash abc",
			),
		).toBe(true);
		expect(
			isRawSearchFetch(
				"python3 .ai-badger/skills/get-raw-text-search/scripts/get_raw_text_search.py --pattern 'foo'",
			),
		).toBe(true);
		expect(
			isRawSearchFetch(
				'python3 get_raw_text_search.py --capture abc123 \'["grep","-n","x"]\'',
			),
		).toBe(false);
		expect(isRawSearchFetch("grep -rn pattern src/")).toBe(false);
		expect(isRawSearchFetch("")).toBe(false);
	});
});

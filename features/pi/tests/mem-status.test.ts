/**
 * The memory-first gate's footer status: the pure counters behind `[mem <searched> <pct>%]`.
 *
 * The gate (ai-badger's memory-first gate) answers a repo text search with the memory result
 * instead of blocking it, and keeps the original grep/rg output alive for about two minutes.
 * The `get-raw-text-search` skill fetches that output. Three numbers say whether the capture is
 * worth its cost: how many searches the gate answered, how many of them it captured raw output
 * for, and how many of those raw results the agent actually fetched — a retrieval that answered
 * `pending` fetched nothing yet, and reading the same handle twice fetched one result.
 *
 * The segment carries the searches the gate answered and the fetched share of the captures as
 * a percentage: a fraction (`9/10`) is a ratio the reader has to divide, and a share with no
 * captures (`0/0`) is a division by zero dressed up as a number.
 */

import { describe, expect, test } from "bun:test";
import {
	capturedHashes,
	countCaptured,
	formatMemStatus,
	isRawSearchFetch,
	readRawFetchOutcome,
	searchedPatterns,
} from "../adjustments/adapter/mem-status.ts";

/** The gate's context: the memory block, then the JSON line it appends. */
function gateContext(entries: Array<{ pattern: string; rawResultHash?: string }>): string {
	const block = [
		'Memory context (ai-raccoon query, snippets — query: "x"):',
		"- memories (snippets — to get full content use get_entry with the hash):",
		"  (no memory hits)",
	].join("\n");
	return `${block}\n\n${JSON.stringify({ textSearchInput: entries })}`;
}

describe("the memory gate's footer status", () => {
	test("the segment is bracketed, in the style the other pi extensions use", () => {
		expect(formatMemStatus({ searched: 12, captured: 10, fetched: 9 })).toBe("[mem 12 90%]");
		expect(formatMemStatus({ searched: 3, captured: 0, fetched: 0 })).toBe("[mem 3 0%]");
	});

	test("the fetched share counts the captures, not the searches", () => {
		expect(formatMemStatus({ searched: 9, captured: 3, fetched: 1 })).toBe("[mem 9 33%]");
		expect(formatMemStatus({ searched: 9, captured: 3, fetched: 3 })).toBe("[mem 9 100%]");
	});

	test("the share is a whole percent", () => {
		expect(formatMemStatus({ searched: 4, captured: 3, fetched: 1 })).toBe("[mem 4 33%]");
		expect(formatMemStatus({ searched: 4, captured: 3, fetched: 2 })).toBe("[mem 4 67%]");
	});

	test("every pattern the gate searched counts, captured or not", () => {
		const context = gateContext([
			{ pattern: "one", rawResultHash: "a".repeat(64) },
			{ pattern: "two" },
			{ pattern: "three" },
		]);
		expect(searchedPatterns([context])).toEqual(["one", "two", "three"]);
	});

	test("a pattern the gate searched twice is one search", () => {
		const context = gateContext([{ pattern: "one", rawResultHash: "a".repeat(64) }]);
		expect(searchedPatterns([context, context])).toEqual(["one"]);
	});

	test("a context without a text-search record searched nothing", () => {
		expect(searchedPatterns(["just a memory block, no JSON tail"])).toEqual([]);
		expect(searchedPatterns([])).toEqual([]);
	});

	test("an empty pattern is not a search", () => {
		const context = gateContext([{ pattern: "" }, { pattern: "  " }, { pattern: "one" }]);
		expect(searchedPatterns([context])).toEqual(["one"]);
		expect(capturedHashes([context])).toEqual([]);
	});

	test("only a pattern with a captured raw output counts as captured", () => {
		const context = gateContext([
			{ pattern: "one", rawResultHash: "a".repeat(64) },
			{ pattern: "two" },
			{ pattern: "three", rawResultHash: "b".repeat(64) },
		]);
		expect(countCaptured([context])).toBe(2);
	});

	test("the captured hashes are the handles a fetch can name", () => {
		const context = gateContext([
			{ pattern: "one", rawResultHash: "a".repeat(64) },
			{ pattern: "two" },
			{ pattern: "three", rawResultHash: "b".repeat(64) },
		]);
		expect(capturedHashes([context])).toEqual(["a".repeat(64), "b".repeat(64)]);
	});

	test("the same pattern captured twice is one capture", () => {
		const context = gateContext([{ pattern: "one", rawResultHash: "a".repeat(64) }]);
		expect(capturedHashes([context, context])).toEqual(["a".repeat(64)]);
	});

	test("a context without a text-search record counts nothing", () => {
		expect(countCaptured(["just a memory block, no JSON tail"])).toBe(0);
		expect(countCaptured([])).toBe(0);
		expect(capturedHashes(["just a memory block, no JSON tail"])).toEqual([]);
	});

	test("an unparseable tail counts nothing and never throws", () => {
		expect(countCaptured(["block\n\n{not json}"])).toBe(0);
		expect(countCaptured(["block\n\n[1,2,3]"])).toBe(0);
	});

	test("every context counts, and the same capture twice counts once", () => {
		const first = gateContext([{ pattern: "one", rawResultHash: "a".repeat(64) }]);
		const second = gateContext([{ pattern: "two", rawResultHash: "b".repeat(64) }]);
		expect(countCaptured([first, second])).toBe(2);
		expect(countCaptured([first, first])).toBe(1);
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

	test("only a ready retrieval counts as a fetch", () => {
		const ready = readRawFetchOutcome([{ type: "text", text: '{"status":"ready","hash":"abc"}' }]);
		expect(ready).toEqual({ ready: true, hash: "abc" });
		const pending = readRawFetchOutcome([{ type: "text", text: '{"status":"pending","hash":"abc"}' }]);
		expect(pending).toEqual({ ready: false, hash: "abc" });
		expect(readRawFetchOutcome([{ type: "text", text: '{"status":"expired","hash":"abc"}' }])?.ready).toBe(false);
		expect(readRawFetchOutcome([{ type: "text", text: '{"status":"error","hash":"abc"}' }])?.ready).toBe(false);
	});

	test("a result that is not a retrieval answer says nothing", () => {
		expect(readRawFetchOutcome([{ type: "text", text: "not json at all" }])).toBeUndefined();
		expect(readRawFetchOutcome([{ type: "text", text: '{"stdout":"hello"}' }])).toBeUndefined();
		expect(readRawFetchOutcome(undefined)).toBeUndefined();
	});

	test("the retrieval answer is read from plain text too", () => {
		expect(readRawFetchOutcome('{"status":"ready","hash":"abc"}')).toEqual({ ready: true, hash: "abc" });
	});
});

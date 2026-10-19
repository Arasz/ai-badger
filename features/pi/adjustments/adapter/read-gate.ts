/**
 * The memory-first read gate: pi's `read` tool is redirected to the ai-raccoon bank before
 * the file is read, the same way the framework's memory-first gate redirects a text search.
 *
 * The bank answers first; the raw file is the fallback the model asks for by re-issuing the
 * read. The gate itself is the framework's own `memory_first_gate_hook.py` — the same script
 * that denies a first-sighting grep — so a read shares the grep gate's searched-pattern
 * store, its project id, and its JSONL log (`~/.ai-badger/memory-first-search/searches.jsonl`).
 * A path the bank already knows is never searched twice, and a path a grep already searched
 * is not searched again for the read.
 *
 * The read reaches that script as a search for the path: the framework gate reads a
 * `search_files` call with a `pattern` as "look this up in the bank first". The payload is
 * the framework's own Claude shape, so the script needs no pi-specific branch.
 *
 * No I/O here: the spawn, the timeout and the fail-open decision live in index.ts.
 */

import { join } from "node:path";
import { parseHookStdout, type ClaudeHookPayload } from "./hook-bridge.ts";

/** The framework's memory-first hook, inside the project. */
export const READ_GATE_SCRIPT = ".ai-badger/skills/ai-raccoon-memory/scripts/memory_first_gate_hook.py";

/** Kill switch: the literal "0" turns the read gate off. */
export const READ_GATE_ENV = "PI_BADGER_READ_GATE";

/** The tool name the framework gate reads as "a search for this pattern". */
const SEARCH_TOOL_NAME = "search_files";

/** What the bank offers when it knows nothing about the file. */
const NO_HITS = "(no hits)";

/** The gate script's path for a project. */
export function readGateScript(cwd: string): string {
	return join(cwd, ...READ_GATE_SCRIPT.split("/"));
}

/** The file path a read names, or null when the call names none. */
export function readPattern(input: Record<string, unknown> | undefined): string | null {
	const path = input?.path;
	if (typeof path !== "string") return null;
	return path.trim() === "" ? null : path;
}

/** The gate's switch: on unless the environment says exactly "0". */
export function readGateEnabled(env: Record<string, string | undefined>): boolean {
	return env[READ_GATE_ENV] !== "0";
}

/** The payload the framework gate reads: a search for the path, in Claude's shape. */
export function readGatePayload(
	path: string,
	ctx: { cwd: string; sessionId: string },
): ClaudeHookPayload {
	return {
		hook_event_name: "PreToolUse",
		session_id: ctx.sessionId,
		cwd: ctx.cwd,
		tool_name: SEARCH_TOOL_NAME,
		tool_input: { pattern: path },
	};
}

/** What the gate produced for one read: let it through, or stop it with a reason. */
export type ReadGateOutcome = { kind: "allow" } | { kind: "block"; reason: string };

/** The memory result the gate's payload carries, or null when it carries none. */
function memoryHits(payload: string): string | null {
	let parsed: unknown;
	try {
		parsed = JSON.parse(payload);
	} catch {
		return null;
	}
	if (typeof parsed !== "object" || parsed === null) return null;
	const result = (parsed as { searchResult?: { mem_search_result_output?: unknown } }).searchResult;
	const hits = result?.mem_search_result_output;
	return typeof hits === "string" ? hits : null;
}

/**
 * The reason the model sees: the file, the bank's answer verbatim, and the way to the raw
 * file. The payload is passed through unchanged — the framework owns its shape.
 */
export function readGateReason(path: string, payload: string): string {
	return [
		`ai-badger memory-first gate (read): the memory bank was searched for ${path} before this file was read.`,
		payload,
		"If the memory context above answers your question, skip the read; otherwise re-issue the same read to get the raw file content.",
	].join("\n");
}

/**
 * The gate's stdout as a decision about the read. Only a bank answer stops the read: a
 * search that found nothing, a bank that could not search, silence, an allow decision and
 * unparseable output all let the read through — the gate never stands between the model and
 * a file it cannot get an answer about.
 */
export function parseReadGateStdout(stdout: string, path: string): ReadGateOutcome {
	const decision = parseHookStdout(stdout);
	if (decision === null || decision.decision !== "deny") return { kind: "allow" };
	const reason = decision.reason;
	if (typeof reason !== "string" || reason === "") return { kind: "allow" };
	const hits = memoryHits(reason);
	if (hits === null) return { kind: "allow" };
	if (hits.trim() === "" || hits.trim() === NO_HITS) return { kind: "allow" };
	return { kind: "block", reason: readGateReason(path, reason) };
}

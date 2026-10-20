/**
 * The memory-first gate's footer status: how many repo text searches the gate captured raw
 * output for, and how many of those raw results the agent fetched.
 *
 * The gate (ai-badger's memory-first gate) answers a repo text search with the memory result
 * instead of blocking it, and keeps the original grep/rg output alive for about two minutes.
 * The `get-raw-text-search` skill fetches that output; a capture nobody fetches is cost
 * without use, so the footer carries both numbers.
 *
 * A fetch counts once, and only when the retrieval answered `ready`: a `pending` answer is
 * the skill's cue to retry, an expired or failed one fetched nothing, and reading the same
 * handle twice fetched one result.
 */

/** The gate's counters for one session. */
export interface MemStatus {
	/** Text searches the gate captured raw output for. */
	captured: number;
	/** Raw results the agent fetched with the get-raw-text-search skill. */
	fetched: number;
}

/** The footer segment, in the bracketed style the other pi extensions use: the number of
 * captured searches, and the share of them the agent fetched, as a percentage. */
export function formatMemStatus(status: MemStatus): string {
	const pct = status.captured > 0 ? Math.round((status.fetched / status.captured) * 100) : 0;
	return `[mem ${status.captured} ${pct}%]`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The captured patterns in one gate context: their handles, in the order the gate listed them. */
function capturedHashesInContext(context: string): string[] {
	for (const line of context.split("\n").reverse()) {
		const trimmed = line.trim();
		if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) continue;
		let parsed: unknown;
		try {
			parsed = JSON.parse(trimmed);
		} catch {
			continue;
		}
		if (!isRecord(parsed)) continue;
		const inputs = parsed.textSearchInput;
		if (!Array.isArray(inputs)) continue;
		return inputs
			.filter(
				(entry) =>
					isRecord(entry) &&
					typeof entry.rawResultHash === "string" &&
					entry.rawResultHash.length > 0,
			)
			.map((entry) => (entry as { rawResultHash: string }).rawResultHash);
	}
	return [];
}

/** Every captured handle across the gate's contexts, each one once, in the order first seen. */
export function capturedHashes(contexts: readonly string[]): string[] {
	const seen = new Set<string>();
	for (const context of contexts) {
		for (const hash of capturedHashesInContext(context)) seen.add(hash);
	}
	return [...seen];
}

/** How many of the gate's recorded patterns carry a captured raw output, across every context. */
export function countCaptured(contexts: readonly string[]): number {
	return capturedHashes(contexts).length;
}

/**
 * True when the command fetches a captured raw result. The gate's own capture worker
 * (`--capture`) is not a fetch: it records the output, it does not read it back.
 */
export function isRawSearchFetch(command: string): boolean {
	if (!command.includes("get_raw_text_search.py")) return false;
	if (command.includes("--capture")) return false;
	return /--pattern(-hash)?\b/.test(command);
}

/** One retrieval's answer: whether the raw result is ready, and the handle it names. */
export interface RawFetchOutcome {
	readonly ready: boolean;
	readonly hash?: string;
}

/** The text of a tool result: its text blocks joined, or the string itself. */
function resultText(content: unknown): string | undefined {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return undefined;
	const parts: string[] = [];
	for (const block of content) {
		if (isRecord(block) && typeof block.text === "string") parts.push(block.text);
	}
	return parts.length > 0 ? parts.join("\n") : undefined;
}

/**
 * The retrieval's answer inside a tool result, when it carries one. A result that is not a
 * retrieval answer (a failure, a tool output that is not the script's JSON) says nothing.
 */
export function readRawFetchOutcome(content: unknown): RawFetchOutcome | undefined {
	const text = resultText(content);
	if (text === undefined) return undefined;
	for (const line of text.split("\n").reverse()) {
		const trimmed = line.trim();
		if (!trimmed.startsWith("{")) continue;
		let parsed: unknown;
		try {
			parsed = JSON.parse(trimmed);
		} catch {
			continue;
		}
		if (!isRecord(parsed)) continue;
		const status = parsed.status;
		if (typeof status !== "string") continue;
		const hash = typeof parsed.hash === "string" && parsed.hash.length > 0 ? parsed.hash : undefined;
		return { ready: status === "ready", hash };
	}
	return undefined;
}

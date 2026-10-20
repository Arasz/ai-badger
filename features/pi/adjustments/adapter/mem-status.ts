/**
 * The memory-first gate's footer status: how many repo text searches the gate captured raw
 * output for, and how many of those raw results the agent fetched.
 *
 * The gate (ai-badger's memory-first gate) answers a repo text search with the memory result
 * instead of blocking it, and keeps the original grep/rg output alive for about two minutes.
 * The `get-raw-text-search` skill fetches that output; a capture nobody fetches is cost
 * without use, so the footer carries both numbers.
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

/** The captured patterns in one gate context: 0 when the context carries no record. */
function capturedInContext(context: string): number {
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
		return inputs.filter(
			(entry) =>
				isRecord(entry) &&
				typeof entry.rawResultHash === "string" &&
				entry.rawResultHash.length > 0,
		).length;
	}
	return 0;
}

/** How many of the gate's recorded patterns carry a captured raw output, across every context. */
export function countCaptured(contexts: readonly string[]): number {
	let captured = 0;
	for (const context of contexts) captured += capturedInContext(context);
	return captured;
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

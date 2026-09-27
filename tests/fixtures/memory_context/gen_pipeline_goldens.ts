/**
 * Prints pipeline_goldens.json to stdout and writes score_fixtures.json to
 * disk, both from pi's query-pipeline TypeScript run under bun. Read-only
 * against the pi checkout: it only imports pi's modules, never writes there.
 *
 * Verify without touching the committed file:
 *   bun tests/fixtures/memory_context/gen_pipeline_goldens.ts | diff - tests/fixtures/memory_context/pipeline_goldens.json
 * Regenerate both committed files:
 *   bun tests/fixtures/memory_context/gen_pipeline_goldens.ts > tests/fixtures/memory_context/pipeline_goldens.json
 * Point at a different pi checkout with `PI_REPO=/path/to/pi bun ...`. CI does not run bun.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";

const PI_REPO = process.env["PI_REPO"] ?? "/Users/arasz/RiderProjects/pi-badger-integration";
const PI_COMMIT = "ee5f1c6e689b988a8924781b3acb5961ce40c326";
const HERE = dirname(new URL(import.meta.url).pathname);

const qp = (name: string): string => join(PI_REPO, "extensions/query-pipeline", name);
const tf = (name: string): string => join(PI_REPO, "tests/query-pipeline/fixtures", name);

type Json = unknown;

const inputs = JSON.parse(readFileSync(join(HERE, "pipeline_golden_inputs.json"), "utf8")) as {
	planner: {
		build_user_prompt_queries: Array<{ id: string; query: string }>;
		parse_plan_corpus: Array<{ id: string; text: string }>;
		fallback_reason_source: string;
	};
	jev: {
		wire_candidate_sets: Array<Record<string, unknown> & { id: string }>;
		classify_cases: Array<{ id: string; status: number; body: string; headers?: Record<string, string>; names?: string[] }>;
		retry_after_headers: Array<{ id: string; header: string | null }>;
		answer_tolerance_body: string;
		answer_tolerance_names: string[];
	};
	merge: {
		merge_select_cases: Array<{ id: string; slots: number; candidates: Json[] }>;
		doc_key_cases: Array<{ id: string; hit: Json }>;
		server_rank_cases: Array<{ id: string; candidates: Json[] }>;
	};
	runner: { scenarios: Array<Record<string, unknown> & { id: string; query: string }> };
};

// ------------------------------------------------------------------ imports (pi source, read-only)

const plannerMod = await import(qp("planner.ts"));
const mergeMod = await import(qp("merge.ts"));
const jevMod = await import(qp("jev-client.ts"));
const pipelineMod = await import(qp("pipeline.ts"));
const scoreFixturesMod = await import(tf("score-fixtures.ts"));

// ------------------------------------------------------------------ planner section

const buildUserPrompt = inputs.planner.build_user_prompt_queries.map((entry) => ({
	id: entry.id,
	output: plannerMod.buildPlannerUserPrompt(entry.query),
}));

const parsePlanResults = inputs.planner.parse_plan_corpus.map((entry) => ({
	id: entry.id,
	output: plannerMod.parsePlan(entry.text),
}));

const planner = {
	delegator_persona: plannerMod.DELEGATOR_PERSONA,
	planner_addendum: plannerMod.PLANNER_ADDENDUM,
	planner_user_prefix: plannerMod.PLANNER_USER_PREFIX,
	fallback_reasons: {
		value: ["no-model", "timeout", "transport", "empty-text", "no-json-object", "invalid-shape"],
		source: inputs.planner.fallback_reason_source,
		note: "PlannerFallbackReason is a TypeScript union type, not a runtime value; this list is a literal transcription of extensions/query-pipeline/types.ts, not a bun-computed output.",
	},
	build_user_prompt: buildUserPrompt,
	parse_plan: parsePlanResults,
};

// ------------------------------------------------------------------ jev section

function repeatCandidate(spec: Record<string, unknown>): Record<string, unknown> {
	const out: Record<string, unknown> = { ...spec };
	if (spec["snippet_repeat"]) {
		const r = spec["snippet_repeat"] as { char: string; count: number };
		out["snippet"] = r.char.repeat(r.count);
		delete out["snippet_repeat"];
	}
	return out;
}

function resolvePrompt(entry: Record<string, unknown>): string {
	if (entry["prompt_repeat"]) {
		const r = entry["prompt_repeat"] as { char: string; count: number };
		return r.char.repeat(r.count);
	}
	return entry["prompt"] as string;
}

function resolveCandidates(entry: Record<string, unknown>): Array<Record<string, unknown>> {
	if (entry["candidates_generated"]) {
		const g = entry["candidates_generated"] as { count: number; hash_prefix: string; ranking_formula?: string };
		return Array.from({ length: g.count }, (_, i) => {
			const cand: Record<string, unknown> = { hash: `${g.hash_prefix}${i}`, path: `docs/${g.hash_prefix}${i}.md`, snippet: `snippet ${g.hash_prefix}${i}`, kind: "memory" };
			if (g.ranking_formula === "50 - index") cand["ranking"] = 50 - i;
			return cand;
		});
	}
	return ((entry["candidates"] as Array<Record<string, unknown>>) ?? []).map(repeatCandidate);
}

// A manual scheduler that never actually delays: attempts always succeed on
// the first try in these golden captures, so no timer ever needs to fire.
function immediateScheduler(): { setTimeout: (h: () => void, ms: number) => unknown; clearTimeout: (h: unknown) => void } {
	return { setTimeout: () => 0, clearTimeout: () => {} };
}

async function captureWireBodies(entry: Record<string, unknown>): Promise<Json[]> {
	const captured: Json[] = [];
	const fetchFn = async (_url: string, init: { body: string }) => {
		captured.push(JSON.parse(init.body));
		return {
			status: 200,
			headers: { get: () => null },
			text: async () => JSON.stringify({ model: "m", answers: {}, usage: { input_tokens: 0, output_tokens: 0, cost: 0 } }),
		};
	};
	const deps = { fetchFn, scheduler: immediateScheduler(), now: () => 0, env: { OPENROUTER_API_KEY: "test-key" } };
	const scorer = jevMod.createJevScorer(deps as never);
	const prompt = resolvePrompt(entry);
	const candidates = resolveCandidates(entry);
	await scorer(prompt, candidates as never, new AbortController().signal, 60_000);
	return captured;
}

const jevWireBodies: Array<{ id: string; requests: Json[] }> = [];
for (const entry of inputs.jev.wire_candidate_sets) {
	jevWireBodies.push({ id: entry.id, requests: await captureWireBodies(entry) });
}

const jevClassify: Array<{ id: string; outcome: Json }> = [];
for (const entry of inputs.jev.classify_cases) {
	const response = {
		status: entry.status,
		headers: { get: (name: string) => entry.headers?.[name.toLowerCase()] ?? null },
		text: async () => entry.body,
	};
	const outcome = await jevMod.classifyScoreResponse(response as never, entry.names ?? ["c0"]);
	jevClassify.push({ id: entry.id, outcome });
}

const jevRetryAfter = inputs.jev.retry_after_headers.map((entry) => ({
	id: entry.id,
	expected_ms: jevMod.clampRetryAfterMs(entry.header),
}));

const jevAnswerTolerance = await jevMod.classifyScoreResponse(
	{ status: 200, headers: { get: () => null }, text: async () => inputs.jev.answer_tolerance_body } as never,
	inputs.jev.answer_tolerance_names,
);

const jev = {
	constants: {
		SCORE_BATCH_MAX: jevMod.SCORE_BATCH_MAX,
		SCORE_ATTEMPTS: jevMod.SCORE_ATTEMPTS,
		SCORE_POOL_MAX: jevMod.SCORE_POOL_MAX,
		SCORE_TIMEOUT_DEFAULT_MS: jevMod.SCORE_TIMEOUT_DEFAULT_MS,
		SCORE_TIMEOUT_MIN_MS: jevMod.SCORE_TIMEOUT_MIN_MS,
		SCORE_TIMEOUT_MAX_MS: jevMod.SCORE_TIMEOUT_MAX_MS,
		WARM_TIMEOUT_MS: jevMod.WARM_TIMEOUT_MS,
		SCORE_STATE_CHAR_CAP: jevMod.SCORE_STATE_CHAR_CAP,
		SCORE_EXCERPT_CHAR_CAP: jevMod.SCORE_EXCERPT_CHAR_CAP,
		SCORE_ENDPOINT_DEFAULT: jevMod.SCORE_ENDPOINT_DEFAULT,
		SCORE_MODEL_DEFAULT: jevMod.SCORE_MODEL_DEFAULT,
		SCORE_QUESTION: jevMod.SCORE_QUESTION,
		SCORE_CRITERIA: jevMod.SCORE_CRITERIA,
		RETRY_AFTER_FLOOR_MS: jevMod.RETRY_AFTER_FLOOR_MS,
		RETRY_AFTER_CEIL_MS: jevMod.RETRY_AFTER_CEIL_MS,
		SCORE_ERROR_KINDS: jevMod.SCORE_ERROR_KINDS,
		SCORE_RETRYABLE_KINDS: jevMod.SCORE_RETRYABLE_KINDS,
		SCORE_NON_RETRYABLE_KINDS: jevMod.SCORE_NON_RETRYABLE_KINDS,
	},
	wire_bodies: jevWireBodies,
	classify: jevClassify,
	retry_after: jevRetryAfter,
	answer_tolerance: jevAnswerTolerance,
};

// ------------------------------------------------------------------ merge section

const mergeSelectResults = inputs.merge.merge_select_cases.map((entry) => {
	const { mem, code } = mergeMod.mergeSelect(entry.candidates as never, entry.slots);
	return { id: entry.id, mem: mem.map((h: { hash: string }) => h.hash), code: code.map((h: { hash: string }) => h.hash) };
});

const docKeyResults = inputs.merge.doc_key_cases.map((entry) => ({ id: entry.id, output: mergeMod.docKey(entry.hit as never) }));

const serverRankResults = inputs.merge.server_rank_cases.map((entry) => {
	const { mem } = mergeMod.mergeSelect(entry.candidates as never, 5);
	return { id: entry.id, order: mem.map((h: { hash: string }) => h.hash) };
});

const merge = {
	merge_select: mergeSelectResults,
	doc_key: docKeyResults,
	server_rank_order: serverRankResults,
};

// ------------------------------------------------------------------ runner section

interface ScenarioSpec {
	id: string;
	query: string;
	plan: { status: "ok"; concepts: Array<{ name: string; queries: string[] }> } | { status: "fallback"; reason: string } | { status: "throw" };
	search: Record<string, Json[] | "throw">;
	score: { mode: "fixed"; scores: Record<string, number> } | { mode: "throw" } | { mode: "null" };
}

function buildPlanFn(spec: ScenarioSpec["plan"]) {
	return async () => {
		if (spec.status === "throw") throw new Error("planner exploded");
		if (spec.status === "ok") return { status: "ok" as const, plan: { concepts: spec.concepts } };
		return { status: "fallback" as const, reason: spec.reason };
	};
}

function buildSearchFn(table: Record<string, Json[] | "throw">) {
	return async (query: string): Promise<string> => {
		const entry = table[query];
		if (entry === "throw" || entry === undefined) throw new Error(`no fixture hits for query ${JSON.stringify(query)}`);
		return JSON.stringify({ data: { results: entry, code: [] } });
	};
}

function buildScoreFn(spec: ScenarioSpec["score"]) {
	return async (_prompt: string, candidates: Array<{ hash: string }>) => {
		if (spec.mode === "throw") throw new Error("jev down");
		if (spec.mode === "null") {
			return { results: candidates.map((c) => ({ hash: c.hash, score: null })), usage: { input_tokens: 0, output_tokens: 0, cost: 0 }, batches: 0 };
		}
		return {
			results: candidates.map((c) => ({ hash: c.hash, score: spec.scores[c.hash] ?? null })),
			usage: { input_tokens: 0, output_tokens: 0, cost: 0 },
			batches: 1,
		};
	};
}

interface RunnerScenarioResult {
	id: string;
	status: string;
	reason: string;
	mem: string[];
	code: string[];
	queries: string[];
	candidates: number;
	scored: number;
}

const runnerScenarios: RunnerScenarioResult[] = [];
for (const raw of inputs.runner.scenarios) {
	const spec = raw as unknown as ScenarioSpec;
	const deps = {
		search: buildSearchFn(spec.search),
		plan: buildPlanFn(spec.plan),
		score: buildScoreFn(spec.score),
		env: { OPENROUTER_API_KEY: "test-key" },
	};
	const result = await pipelineMod.runPipeline(deps as never, { query: spec.query });
	runnerScenarios.push({
		id: spec.id,
		status: result.status,
		reason: result.reason,
		mem: result.mem.map((h: { hash: string }) => h.hash),
		code: result.code.map((h: { hash: string }) => h.hash),
		queries: result.queries,
		candidates: result.candidates,
		scored: result.scored,
	});
}

const runner = {
	scenarios: runnerScenarios,
	reasons_observed: [...new Set(runnerScenarios.map((s) => s.reason))].sort(),
};

// ------------------------------------------------------------------ score_fixtures.json (every value export)

const scoreFixtures = {
	MEASURED_CRITERIA: scoreFixturesMod.MEASURED_CRITERIA,
	MEASURED_QUESTION: scoreFixturesMod.MEASURED_QUESTION,
	MEASURED_PROMPT: scoreFixturesMod.MEASURED_PROMPT,
	MEASURED_SCORE_REQUEST: scoreFixturesMod.MEASURED_SCORE_REQUEST,
	MEASURED_SCORE_ANSWER: scoreFixturesMod.MEASURED_SCORE_ANSWER,
	SYNTH_SCORE_BAD_REQUEST_BODY: scoreFixturesMod.SYNTH_SCORE_BAD_REQUEST_BODY,
	SYNTH_SCORE_UNAUTHORIZED_BODY: scoreFixturesMod.SYNTH_SCORE_UNAUTHORIZED_BODY,
	SYNTH_SCORE_PAYMENT_REQUIRED_BODY: scoreFixturesMod.SYNTH_SCORE_PAYMENT_REQUIRED_BODY,
	SYNTH_SCORE_RATE_LIMITED_BODY: scoreFixturesMod.SYNTH_SCORE_RATE_LIMITED_BODY,
	SYNTH_SCORE_SERVER_ERROR_BODY: scoreFixturesMod.SYNTH_SCORE_SERVER_ERROR_BODY,
	SYNTH_SCORE_ERROR_ENVELOPE: scoreFixturesMod.SYNTH_SCORE_ERROR_ENVELOPE,
	SYNTH_SCORE_TRUNCATED_JSON: scoreFixturesMod.SYNTH_SCORE_TRUNCATED_JSON,
	SYNTH_SCORE_PARTIAL_ANSWERS_BODY: scoreFixturesMod.SYNTH_SCORE_PARTIAL_ANSWERS_BODY,
	SYNTH_SCORE_WRONG_SHAPES_BODY: scoreFixturesMod.SYNTH_SCORE_WRONG_SHAPES_BODY,
	pi_commit: PI_COMMIT,
	generator: "gen_pipeline_goldens.ts",
	bun: Bun.version,
};

// ------------------------------------------------------------------ leak self-check (J9 parity)

const classifyLeakCheck = JSON.stringify(jevClassify);
if (classifyLeakCheck.includes("SECRET-BODY-MARKER")) {
	throw new Error("pi's classifyScoreResponse leaked the SYNTH body marker into a golden — investigate before committing");
}

// ------------------------------------------------------------------ write outputs

const goldens = {
	pi_commit: PI_COMMIT,
	generator: "gen_pipeline_goldens.ts",
	bun: Bun.version,
	planner,
	jev,
	merge,
	runner,
};

writeFileSync(join(HERE, "score_fixtures.json"), `${JSON.stringify(scoreFixtures, null, 2)}\n`);
process.stderr.write(`wrote score_fixtures.json from pi ${PI_COMMIT} under bun ${Bun.version}; pipeline_goldens.json printed to stdout\n`);
process.stdout.write(`${JSON.stringify(goldens, null, 2)}\n`);

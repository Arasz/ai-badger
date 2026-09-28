// Prints pi's toMemoryContext output for every case in golden_inputs.json.
// Run under bun against rag-core.ts at the pinned pi commit; CI never runs it:
//   bun gen_goldens.ts <rag-core.ts> <golden_inputs.json> <pi commit> > golden_outputs.json
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const [ragCorePath, inputsPath, piCommit] = process.argv.slice(2);
if (!ragCorePath || !inputsPath || !piCommit) {
	console.error("usage: bun gen_goldens.ts <rag-core.ts> <golden_inputs.json> <pi commit>");
	process.exit(2);
}

const { toMemoryContext } = await import(resolve(ragCorePath));
const inputs = JSON.parse(readFileSync(inputsPath, "utf8")) as {
	cases: Record<string, { query: string; mem: unknown[]; code: unknown[] }>;
};

const outputs: Record<string, string> = {};
for (const [name, c] of Object.entries(inputs.cases)) {
	outputs[name] = toMemoryContext(c.query, c.mem, c.code);
}

process.stdout.write(
	`${JSON.stringify({ pi_commit: piCommit, generator: "gen_goldens.ts", bun: Bun.version, outputs }, null, 2)}\n`,
);

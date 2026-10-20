#!/usr/bin/env python3
"""Live check of the memory-gate fixes (ADR-0045) in a real pi session (2026-10-20).

Three live checks against the real ai-raccoon bank, the real project hooks and the real pi
harness (pi 1.3.0, the ai-badger adapter as installed at user scope):

A. The gate's memory result rides the tool result — a live pi run with the FIXED adapter
   (0.210.0): the block is in the tool result, no user-role message carries it, one user
   message in the whole session, one agent run.
B. The same live run with the PRE-FIX adapter (0.209.0): the block travels as a
   user-role follow-up message and costs a second agent run. This is the control: a check
   nobody has seen fail is not a check.
C. The prompt hook refuses to search its own block — the real hook script, fed a real
   block from the real bank, answers with nothing; an ordinary prompt still gets a block.

Usage: live.py <outdir>
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/Users/arasz/RiderProjects/ai-badger")
EXT = Path.home() / ".pi" / "agent" / "extensions" / "ai-badger"
ADAPTER = REPO / "features" / "pi" / "adjustments" / "adapter"
SCRIPTS = REPO / ".ai-badger" / "skills" / "ai-raccoon-memory" / "scripts"
PRE_FIX_REV = "62479893^"          # the commit before the fix landed
FIXED_REV = "62479893"             # the fix itself
MODEL = "openrouter/openrouter/free"   # the only provider that calls tools in this harness
BLOCK = "Memory context (ai-raccoon memory_search"
SEARCH_LOG = Path.home() / ".ai-badger" / "memory-first-search" / "searches.jsonl"
CANDIDATES = ["memory_broker", "design-tests", "review-tests", "explore-codebase",
              "evidence-first-research", "documentation-drift-audit", "multi-lane-report-assembly",
              "owner-gate-review", "spec-driven-refactoring", "quick-task", "refactor-safely",
              "code-review-checklist", "code-review-evidence", "artifact-verification",
              "browser-usage", "call-behaviorist", "hermes-agent-author", "cron-watchdog-authoring",
              "complete-project-scope-code-review", "differential-feature-refactor",
              "review-gate-diff-verification", "scripts-tooling-refactor", "documentation",
              "design-gate-audit", "debug-issue", "create-task-spec"]
# A pattern the bank has never heard of: the gate has nothing to hand the model, so the
# call is denied — the blocked-call case, where nothing may be stashed for later.
NO_HIT_PATTERN = "zzq_no_such_identifier_9f3c"


def load(name, path):
    """One module by path, under a private name.

    The scripts directory joins `sys.path` first: the gate imports its vendored
    `badger_store` by name, and without it the gate falls back to the file store while the
    hook process uses the database — two different views of what has been searched.
    """
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_show(rev, name):
    """One file's content at *rev*."""
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{name}"],
                          capture_output=True, text=True, check=True).stdout


def install(rev):
    """Install the pi adapter as it stood at *rev* (None: the working tree) at user scope."""
    for item in ADAPTER.iterdir():
        if not item.is_file() or item.suffix not in (".ts", ".json"):
            continue
        target = EXT / item.name
        if rev is None:
            shutil.copy2(item, target)
        else:
            target.write_text(git_show(rev, f"features/pi/adjustments/adapter/{item.name}"),
                              encoding="utf-8")
    return sorted(p.name for p in EXT.iterdir() if p.suffix in (".ts", ".json"))


def pick_pattern(gate):
    """A pattern the gate has not searched for this project and that the bank answers."""
    project = gate.project_id(str(REPO))
    for pattern in CANDIDATES:
        if not gate.unsearched(project, [pattern]):
            continue
        query, _ = gate.search_query([pattern])
        if gate.memory_hits(query, project, "live-probe", 8.0):
            return pattern
    raise SystemExit("no unseen pattern with memory hits — add one to CANDIDATES")


def run_pi(prompt, session_dir):
    """One headless pi run in the repo; the JSONL event stream as a list of records."""
    cmd = ["pi", "-p", "--mode", "json", "--model", MODEL,
           "--tools", "grep,read", "--no-mcp", "--session-dir", str(session_dir), prompt]
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                          timeout=900, check=False)
    records = []
    for line in proc.stdout.splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return proc, records


def texts(content):
    """Every text in a message content (string or block list)."""
    if isinstance(content, str):
        return [content]
    out = []
    for block in content or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            out.append(block["text"])
    return out


def analyze(records):
    """What the session actually carried: roles, blocks, turns."""
    out = {
        "agent_runs": sum(1 for r in records if r.get("type") == "agent_start"),
        "turns": sum(1 for r in records if r.get("type") == "turn_start"),
        "user_messages": [],
        "assistant_messages": 0,
        "tool_results_with_block": 0,
        "tool_results": 0,
        "user_messages_with_block": 0,
        "messages_with_block": [],
        "custom_messages": [],
    }
    for rec in records:
        if rec.get("type") != "message_end":
            continue
        message = rec.get("message") or {}
        role = message.get("role")
        body = "\n".join(texts(message.get("content")))
        if role == "user":
            out["user_messages"].append(body)
            if BLOCK in body:
                out["user_messages_with_block"] += 1
        elif role == "toolResult":
            out["tool_results"] += 1
            if BLOCK in body:
                out["tool_results_with_block"] += 1
        elif role == "assistant":
            out["assistant_messages"] += 1
        if role in ("user", "custom") and BLOCK in body:
            out["messages_with_block"].append({"role": role,
                                              "customType": message.get("customType"),
                                              "head": body[:120]})
        if role == "custom":
            out["custom_messages"].append({
                "customType": message.get("customType"),
                "has_block": BLOCK in body,
                "head": body[:160],
            })
    return out


def log_entries(pattern):
    """The gate's own search log rows that mention *pattern*."""
    if not SEARCH_LOG.exists():
        return []
    return [line for line in SEARCH_LOG.read_text(encoding="utf-8").splitlines()
            if pattern in line]


def live_pi_run(label, rev, gate, outdir):
    """One live pi run with the adapter at *rev*; the findings, with the gate's own log."""
    pattern = pick_pattern(gate)
    before = len(log_entries(pattern))
    install(rev)
    session_dir = Path("/tmp/memgate-live-sessions") / f"session-{label}"
    session_dir.mkdir(parents=True, exist_ok=True)
    prompt = (f"Use the grep tool exactly once, with pattern {pattern} "
              f"and path features, then stop.")
    proc, records = run_pi(prompt, session_dir)
    (outdir / f"{label}.jsonl").write_text(proc.stdout, encoding="utf-8")
    (outdir / f"{label}.stderr").write_text(proc.stderr, encoding="utf-8")
    analysis = analyze(records)
    rows = log_entries(pattern)
    return {
        "label": label,
        "adapter_rev": rev,
        "pattern": pattern,
        "prompt": prompt,
        "exit": proc.returncode,
        "gate_log_rows": len(rows) - before,
        "gate_log_head": (rows[-1][:400] if rows else ""),
        "analysis": analysis,
        "verdict": {
            "gate_fired": (analysis["tool_results_with_block"] > 0
                           or bool(analysis["messages_with_block"])),
            "block_in_tool_result": analysis["tool_results_with_block"] > 0,
            "block_in_message": bool(analysis["messages_with_block"]),
            "block_spoke_as_user": analysis["user_messages_with_block"] > 0,
            "user_messages": len(analysis["user_messages"]),
            "assistant_messages": analysis["assistant_messages"],
            "turns": analysis["turns"],
            "agent_runs": analysis["agent_runs"],
        },
    }


def live_hook_guard(gate):
    """The framework's own prompt hook, live: a block as the prompt gets no block back."""
    hook = SCRIPTS / "memory_context_hook.py"
    project = gate.project_id(str(REPO))
    query, _ = gate.search_query(["memory_first_gate"])
    block = gate.memory_hits(query, project, "live-probe", 8.0)
    env = dict(os.environ, AI_BADGER_MEMORY_CONTEXT_PIPELINE="0")
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": block,
               "session_id": "live-probe", "cwd": str(REPO)}

    def run(prompt):
        proc = subprocess.run([sys.executable, str(hook)], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=120,
                              env=env, cwd=str(REPO), check=False)
        return proc.stdout.strip()

    as_block = run(block)
    payload["prompt"] = ("Please summarise what the memory-first gate in this repository "
                         "does and where its decision is made.")
    ordinary = run(payload["prompt"])
    return {
        "block_used_as_prompt": block[:200] if block else None,
        "output_for_block_prompt": as_block,
        "output_for_ordinary_prompt": ordinary[:400],
        "verdict": {
            "block_prompt_not_enriched": as_block == "",
            "ordinary_prompt_still_enriched": BLOCK in ordinary,
        },
    }


def live_no_hit_call(gate, outdir):
    """A live run whose pattern the bank cannot answer: the gate has nothing to hand the
    model, so it lets the call through and carries nothing — nothing may ride along to a
    later call.

    The memory gate never denies in a context host (ADR-0017): a host that carries
    model-side context always gets the search through. A *blocked* call's no-leak property
    is therefore not reachable live here; it stays covered by the unit test.
    """
    install(FIXED_REV)
    session_dir = Path("/tmp/memgate-live-sessions") / "session-blocked"
    session_dir.mkdir(parents=True, exist_ok=True)
    prompt = (f"Use the grep tool exactly once, with pattern {NO_HIT_PATTERN} "
              f"and path features, then stop.")
    proc, records = run_pi(prompt, session_dir)
    (outdir / "no_hit.jsonl").write_text(proc.stdout, encoding="utf-8")
    analysis = analyze(records)
    bodies = []
    for rec in records:
        if rec.get("type") != "message_end":
            continue
        body = "\n".join(texts((rec.get("message") or {}).get("content")))
        if body:
            bodies.append(body)
    denials = [b[:220] for b in bodies
               if "memory-first" in b or "denied" in b.lower() or "blocked" in b.lower()]
    return {
        "pattern": NO_HIT_PATTERN,
        "prompt": prompt,
        "exit": proc.returncode,
        "analysis": analysis,
        "denial_text": denials[:2],
        "verdict": {
            "no_block_content_anywhere": (analysis["tool_results_with_block"] == 0
                                           and not analysis["messages_with_block"]),
            "tool_call_was_allowed": analysis["tool_results"] > 0,
        },
    }


def main():
    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    gate = load("gate", SCRIPTS / "memory_first_gate.py")
    results = {}

    results["prefix"] = live_pi_run("prefix", PRE_FIX_REV, gate, outdir)
    results["postfix"] = live_pi_run("postfix", FIXED_REV, gate, outdir)
    results["hook_guard"] = live_hook_guard(gate)
    results["no_hit_call"] = live_no_hit_call(gate, outdir)

    install(None)   # leave the user-scope extension on the current working tree
    (outdir / "live.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    for key in ("prefix", "postfix"):
        print(key, json.dumps(results[key]["verdict"]))
    print("hook_guard", json.dumps(results["hook_guard"]["verdict"]))
    print("no_hit_call", json.dumps(results["no_hit_call"]["verdict"]))
    print("wrote", outdir / "live.json")


if __name__ == "__main__":
    main()

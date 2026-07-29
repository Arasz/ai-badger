"""Hermes plugin hooks for ai-badger framework integration.

Provides feature-parity with Claude Code hooks:
- on_session_start: drift notice (Tier 1, ADR-0001 decision 5)
- pre_llm_call: inject framework version context, usage hints, and MCP tool index recommendations
- post_tool_call: log tool usage, index hit/miss metrics, and learned-skill sync

Installation: `welcome-ai-badger` copies this file and learned_skills_sync.py into
~/.hermes/plugins/ (features/hermes/adjustments/adjust_hooks.py); Hermes discovers
plugins there via the register() entry point.

The plugin self-locates the framework root with the shared `_bootstrap_lib()` shim. In
~/.hermes/plugins/ there is no framework above these two loose files, so the root recorded
in the project's .ai-badger/manifest.json is what answers (ADR-0007).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml  # pylint: disable=import-error

# debug_log sits beside this file in every deployment shape; it is a no-op unless the
# call-behaviorist skill has switched debug on.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import debug_log  # pylint: disable=import-error
except ImportError:  # pragma: no cover - a missing logger must never break a hook
    debug_log = None

logger = logging.getLogger("ai_badger_hooks")


def _debug(component: str, event: str, **fields) -> None:
    """Record that a hook ran. Silent when debug is off or the logger is unavailable."""
    if debug_log is not None:
        debug_log.log_event(component, event, **fields)


# ---------------------------------------------------------------------------
# Framework root discovery — the shim every ai-badger entry point carries
# ---------------------------------------------------------------------------

def _bootstrap_lib() -> Path:
    """Put the framework's engine/ and tooling/ on sys.path and return its root.

    One predicate, shared with badger_lib.is_framework_root: schemas/ + features/ +
    engine/badger_lib.py. Ordered inputs: --root, an ancestor walk, $AI_BADGER, the root
    recorded in a .ai-badger/manifest.json above this file, then ~/.ai-badger/framework
    (ADR-0009). Duplicated verbatim in every entry point because locating badger_lib is
    what it is for.
    """
    def is_root(path):
        return ((path / "schemas").is_dir() and (path / "features").is_dir()
                and (path / "engine" / "badger_lib.py").is_file())

    def argv_root():
        # sys.argv is ours only when this file is the program being run; these modules are
        # also imported into hosts whose own --root means something else entirely.
        try:
            if not sys.argv or Path(sys.argv[0]).resolve() != Path(__file__).resolve():
                return None
        except (OSError, ValueError):
            return None
        argv = sys.argv[1:]
        for i, arg in enumerate(argv):
            if arg == "--root" and i + 1 < len(argv):
                return argv[i + 1]
            if arg.startswith("--root="):
                return arg.split("=", 1)[1]
        return None

    def checked(value, source):
        root = Path(value).expanduser()
        if not is_root(root):
            raise RuntimeError(
                f"{source} is {root}, which is not an ai-badger framework root "
                f"(no schemas/ + features/ + engine/badger_lib.py)"
            )
        return root

    def manifests(start):
        # Above this file only. A working directory belongs to whatever repo the user
        # opened, and no repo may steer the sys.path of a hook that runs on session start.
        for anc in [start, *start.parents]:
            manifest = (anc / "manifest.json" if anc.name == ".ai-badger"
                        else anc / ".ai-badger" / "manifest.json")
            if not manifest.is_file():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                yield manifest, data

    def recorded(start):
        for manifest, data in manifests(start):
            value = data.get("frameworkRoot")
            if not value:
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = manifest.parent.parent / candidate
            if is_root(candidate):
                return candidate.resolve()
        return None

    def warn_on_cache_skew(root, start):
        # The cache is last in the order and never updated in place, so its engine can be
        # many releases behind the caller. Say so; never break a session over it.
        if root.resolve() != cache.resolve():
            return
        try:
            have = (cache / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            return
        want = next((d.get("frameworkVersion") for _, d in manifests(start)
                     if d.get("frameworkVersion")), None)
        if have and want and have != want:
            print(f"ai-badger: {cache} is version {have}, but this project was scaffolded "
                  f"by {want}. The cache is never updated in place — remove it, or pass "
                  f"--root <framework checkout>.", file=sys.stderr)

    here = Path(__file__).resolve()
    cache = Path.home() / ".ai-badger" / "framework"
    value = argv_root()
    if value:
        root = checked(value, "--root")
    else:
        root = next((anc for anc in [here, *here.parents] if is_root(anc)), None)
        if root is None and os.environ.get("AI_BADGER"):
            root = checked(os.environ["AI_BADGER"], "$AI_BADGER")
        root = root or recorded(here) or (cache if is_root(cache) else None)
    if root is None:
        raise RuntimeError(
            f"could not locate the ai-badger framework: none above {here.parent}, no "
            f"$AI_BADGER, no frameworkRoot in a .ai-badger/manifest.json above it, and no "
            f"cache at {cache} — pass --root <framework> or clone "
            f"https://github.com/Arasz/ai-badger"
        )
    warn_on_cache_skew(root, here)
    sys.path.insert(0, str(root / "tooling"))
    sys.path.insert(0, str(root / "engine"))
    return root.resolve()


try:
    FRAMEWORK_ROOT: Optional[Path] = _bootstrap_lib()
except RuntimeError:  # a hook degrades to silence; it never breaks a session
    FRAMEWORK_ROOT = None


def _copy_skew_refusal() -> Optional[str]:
    """Why these copies must not run, or None. Warns in passing when the skew is not material.

    Shape D only: any other deployment has no installer record beside this file, so
    `badger_lib.copy_skew` returns OK and this costs one missing-file stat.
    """
    if FRAMEWORK_ROOT is None:
        return None
    try:
        import badger_lib as bl  # pylint: disable=import-outside-toplevel  # needs the bootstrap
        verdict, message = bl.copy_skew(Path(__file__).resolve().parent, FRAMEWORK_ROOT)
    except (AttributeError, ImportError, OSError, ValueError):
        return None  # a staleness check never decides whether the plugin loads
    if verdict == bl.COPY_SKEW_REFUSE:
        return message
    if verdict == bl.COPY_SKEW_WARN:
        print(f"ai-badger: {message}", file=sys.stderr)
    return None


COPY_SKEW_REFUSAL: Optional[str] = _copy_skew_refusal()


# ---------------------------------------------------------------------------
# Drift notice — equivalent to Claude's SessionStart drift_notice_hook.py
# ---------------------------------------------------------------------------

def _read_framework_version() -> Optional[str]:
    """Read the framework's VERSION file, or None on any error."""
    if FRAMEWORK_ROOT is None:
        return None
    try:
        return (FRAMEWORK_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _project_cwd(cwd: str = "") -> str:
    """Resolve the project directory for a hook callback.

    Hermes passes no `cwd` to any plugin hook, so the process working directory is the
    only signal available. See issue #76.
    """
    return cwd or os.getcwd()


def _read_scaffold_version(cwd: Optional[str]) -> Optional[str]:
    """Read the project's manifest.json frameworkVersion, or None."""
    if not cwd:
        return None
    manifest = Path(cwd) / ".ai-badger" / "manifest.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data.get("frameworkVersion")
    except (OSError, ValueError):
        return None


# Hints already injected in this session; cleared at session start.
_session_hints_shown: set = set()


def reset_session_hints() -> None:
    """Forget which one-per-session hints have been shown."""
    _session_hints_shown.clear()


def on_session_start_drift_notice(cwd: str = "", **_kwargs: Any) -> None:
    """Check for framework version drift on every session start.

    Silent on match, on an unscaffolded project, and on any read error.
    A hook that breaks session start or nags unconditionally defeats its purpose.
    """
    reset_session_hints()
    project = _project_cwd(cwd)
    _debug("ai_badger_hooks/session_start", "start", project=project)
    scaffold_ver = _read_scaffold_version(project)
    fw_version = _read_framework_version()
    if not scaffold_ver or not fw_version or scaffold_ver == fw_version:
        _debug("ai_badger_hooks/session_start", "skip", project=project,
               scaffold_version=scaffold_ver, framework_version=fw_version)
        return
    _debug("ai_badger_hooks/session_start", "drift", project=project,
           scaffold_version=scaffold_ver, framework_version=fw_version)
    logger.info(
        "ai-badger drift: scaffolded with %s, framework is %s. "
        "Run den-refresh to update.",
        scaffold_ver, fw_version,
    )


# ---------------------------------------------------------------------------
# MCP Tool Index integration
# ---------------------------------------------------------------------------

# Keyword → tag mapping for extracting domain tags from natural-language queries.
# Mirrors the heuristics in the Phase 0.2 spike (scripts/spike_mcp_match.py).
_KEYWORD_TAG_MAP: dict[str, list[str]] = {
    # Language keywords
    "c#": ["csharp"], ".net": ["dotnet", "csharp"], "dotnet": ["dotnet", "csharp"],
    "csharp": ["csharp"], "typescript": ["typescript"], "ts": ["typescript"],
    "sql": ["sql", "database"], "javascript": ["javascript"], "python": ["python"],

    # Action keywords
    "build": ["build", "dotnet"], "compile": ["build", "dotnet"],
    "run": ["run"], "execute": ["run"], "test": ["run"],
    "refactor": ["refactoring"], "rename": ["refactoring"],
    "format": ["refactoring"],
    "search": ["search"], "find": ["search"], "look for": ["search"],
    "grep": ["search"], "regex": ["search"],
    "read": ["read"], "show": ["read"], "display": ["read"],
    "write": ["write"], "create": ["write"], "make": ["write"],
    "edit": ["write"], "patch": ["write"], "replace": ["write"],

    # Domain keywords
    "database": ["database", "sql"], "db": ["database", "sql"],
    "table": ["database", "sql"], "schema": ["database", "sql"],
    "column": ["database", "sql"], "columns": ["database", "sql"],
    "query": ["database", "sql"], "connection": ["database", "sql"],
    "error": ["diagnostic"], "problem": ["diagnostic"], "warning": ["diagnostic"],
    "bug": ["diagnostic"], "debug": ["diagnostic"],
    "inspect": ["diagnostic"], "check": ["diagnostic"], "diagnostic": ["diagnostic"],
    "trace": ["tracing", "opentelemetry"], "span": ["tracing", "opentelemetry"],
    "log": ["tracing", "opentelemetry"], "opentelemetry": ["tracing", "opentelemetry"],
    "service": ["tracing", "opentelemetry"],
    "file": ["files"], "directory": ["files"], "folder": ["files"],
    "tree": ["files", "navigation"], "structure": ["files", "navigation"],
    "project": ["files", "dotnet"], "solution": ["dotnet", "csharp"],
    "class": ["semantic", "csharp"], "method": ["semantic", "csharp"],
    "symbol": ["semantic"], "reference": ["semantic"],
    "open": ["navigation"], "editor": ["navigation"], "tab": ["navigation"],
    "terminal": ["terminal"], "shell": ["terminal"], "command": ["terminal"],
}


def _load_mcp_index(cwd: Optional[str]) -> Optional[dict[str, Any]]:
    """Load .ai-badger/mcp-tools.yaml from the project, or None."""
    if not cwd:
        return None
    index_path = Path(cwd) / ".ai-badger" / "mcp-tools.yaml"
    if not index_path.exists():
        return None
    try:
        return yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _extract_query_tags(query: str) -> Counter[str]:
    """Extract tags from a natural-language query using keyword matching."""
    lower = query.lower()
    tags: Counter[str] = Counter()
    for keyword, tag_list in _KEYWORD_TAG_MAP.items():
        if keyword in lower:
            for tag in tag_list:
                tags[tag] += 1
    return tags


# A scored tool must exceed this to be considered a match — the "bar" hit/gate telemetry
# refers to. Named so a later change is attributable instead of a silent re-tune.
_MCP_MATCH_THRESHOLD = 0.0

# The component new retrieval events log under — reusing the file's existing component
# name, not inventing one behaviorist.py's orphaned-wiring check would flag as unexpected.
_MCP_RETRIEVAL_COMPONENT = "ai_badger_hooks/mcp_retrieval"

# Wire keys for retrieval telemetry, registered in debug_log.KEY_NAMES; the words live there.
_KEY_QUERY = "q"
_KEY_TERMS = "g"
_KEY_CANDIDATES = "d"
_KEY_TOP = "o"
_KEY_RETURNED = "r"
_KEY_THRESHOLD = "h"
_KEY_TOOL = "l"


def _score_all_tools(query: str, index: dict[str, Any]) -> list[tuple[str, float]]:
    """Every non-removed tool in the index, scored against `query`, sorted descending.

    Unfiltered by threshold: gate telemetry needs the near-misses, not just the winners.
    """
    query_tags = _extract_query_tags(query)
    lower_query = query.lower()
    query_words = set(lower_query.split())
    scored: list[tuple[str, float]] = []

    for server in index.get("sources", []):
        sname = server["name"]
        for tname, tool in server.get("tools", {}).items():
            # Skip removed tools
            if tool.get("status") == "removed":
                continue

            full_name = f"{sname}:{tname}"
            tool_tags = tool.get("tags", [])
            intent = tool.get("intent", "")

            score = 0.0

            # Tag intersection: weighted by keyword frequency
            for tag in tool_tags:
                score += query_tags.get(tag, 0) * 1.0

            # Intent word overlap: raw query words appearing in intent text
            intent_lower = intent.lower()
            for word in query_words:
                if len(word) > 2 and word in intent_lower:
                    score += 0.4

            # Bonus for direct keyword→tag mapping
            for tag in tool_tags:
                if tag in query_tags:
                    score += 0.3

            scored.append((full_name, score))

    scored.sort(key=lambda x: -x[1])
    return scored


def _find_relevant_tools(
    query: str, index: dict[str, Any], top_n: int = 5
) -> list[tuple[str, float]]:
    """Rank all tools in the index by relevance to the query.

    Returns list of (full_tool_name, score) sorted by descending score.
    """
    if not _extract_query_tags(query):
        return []
    scored = [(name, score) for name, score in _score_all_tools(query, index)
              if score > _MCP_MATCH_THRESHOLD]
    return scored[:top_n]


def _index_tool_count(index: dict[str, Any]) -> int:
    """Count of non-removed tools across every source in the index."""
    return sum(
        1
        for server in index.get("sources", [])
        for tool in server.get("tools", {}).values()
        if tool.get("status") != "removed"
    )


def _format_top_candidates(scored: list[tuple[str, float]], limit: int = 3) -> str:
    """`name:score` for the `limit` highest-scoring candidates, comma-joined.

    Capped at 3, not 5: three triples fit the 200-char per-field budget, five do not.
    """
    return ",".join(f"{name}:{score:.2f}" for name, score in scored[:limit])


def _record_retrieval(project, query: str, index: dict, ranked: list) -> None:
    """Record what the retrieval did. Costs nothing when debug is off.

    `no_terms` is not `gate`: the keyword map can return nothing, in which case no
    candidate is ever compared to the threshold, and the top scorer is often a correct
    match the map suppressed. Reporting that as a threshold miss would misattribute the
    very failure this telemetry exists to count.
    """
    if debug_log is None or not debug_log.enabled_for(project):
        return
    terms = _extract_query_tags(query)
    scored = _score_all_tools(query, index)
    common = {
        _KEY_QUERY: query,
        _KEY_CANDIDATES: _index_tool_count(index),
        _KEY_TOP: _format_top_candidates(scored),
    }
    if not terms:
        _debug(_MCP_RETRIEVAL_COMPONENT, "no_terms", project=project,
               **{**common, _KEY_RETURNED: ""})
        return
    scoring = {**common, _KEY_TERMS: ",".join(sorted(terms)),
               _KEY_THRESHOLD: _MCP_MATCH_THRESHOLD}
    if ranked:
        _debug(_MCP_RETRIEVAL_COMPONENT, "hit", project=project,
               **{**scoring, _KEY_RETURNED: ", ".join(name for name, _ in ranked)})
    else:
        _debug(_MCP_RETRIEVAL_COMPONENT, "gate", project=project,
               **{**scoring, _KEY_RETURNED: ""})


# ---------------------------------------------------------------------------
# Context enrichment — equivalent to Claude's UserPromptSubmit hook
# ---------------------------------------------------------------------------

def pre_llm_inject_context(
    cwd: str = "", message: str = "", user_message: str = "", **_kwargs: Any
) -> Optional[Dict[str, str]]:
    """Inject ai-badger framework context into every LLM turn.

    Returns a context dict that Hermes prepends to the user message,
    or None to leave the prompt unchanged. This fires once per turn,
    before the tool-calling loop.

    What we inject:
    - Framework version info (so the agent knows which ai-badger features are available)
    - Drift notice if the project is behind
    - Hermes-specific usage hints (/usage, hermes insights, session_search)
    - MCP tool index recommendations (when .ai-badger/mcp-tools.yaml exists)
    - A pending commit-reminder nudge stashed by post_tool_observer, surfaced once
    """
    parts: list[str] = []
    project = _project_cwd(cwd)
    prompt = message or user_message

    pending_reminder = _pop_pending_reminder(project)
    if pending_reminder:
        parts.append(pending_reminder)

    # Framework version
    fw_version = _read_framework_version()
    if fw_version:
        scaffold_ver = _read_scaffold_version(project)
        if scaffold_ver and scaffold_ver != fw_version:
            parts.append(
                f"[ai-badger] Scaffolded with {scaffold_ver}, "
                f"framework is {fw_version}. Run den-refresh to update."
            )

    # Usage hints — once per session. Repeated every turn, they became wallpaper: the
    # 0.18.0 changelog records an unconditional line as why a broken hook went unnoticed.
    if not _session_hints_shown:
        _session_hints_shown.add("usage")
        parts.append(
            "[Hermes] Use /usage for token consumption and model info. "
            "Use hermes insights --days 7 for weekly analytics. "
            "Use session_search to recall past decisions."
        )

    # MCP tool index recommendations
    if prompt:
        index = _load_mcp_index(project)
        if index is None:
            _debug(_MCP_RETRIEVAL_COMPONENT, "absent", project=project,
                   **{_KEY_QUERY: prompt})
        else:
            ranked = _find_relevant_tools(prompt, index, top_n=5)
            if ranked:
                tools_str = ", ".join(
                    f"{name} ({', '.join(tags_for_display(name, index))})"
                    for name, _ in ranked[:5]
                )
                # Keep under 300 chars to avoid prompt bloat
                hint = f"[ai-badger] Relevant MCP tools: {tools_str}"
                if len(hint) > 300:
                    # Truncate to top 3
                    tools_str_short = ", ".join(
                        f"{name}" for name, _ in ranked[:3]
                    )
                    hint = f"[ai-badger] Relevant MCP tools: {tools_str_short}"
                parts.append(hint)
            _record_retrieval(project, prompt, index, ranked)

    if not parts:
        return None
    return {"context": "\n".join(parts)}


def tags_for_display(tool_name: str, index: dict[str, Any]) -> list[str]:
    """Helper to look up tags for a tool in the index. Used in pre_llm_inject_context."""
    if ":" in tool_name:
        sname, tname = tool_name.split(":", 1)
        for server in index.get("sources", []):
            if server["name"] == sname:
                tool = server.get("tools", {}).get(tname, {})
                return tool.get("tags", [])
    return []


# ---------------------------------------------------------------------------
# Learned-skill sync — wiring only; logic lives in learned_skills_sync.py
# ---------------------------------------------------------------------------

SKILL_MANAGE_TOOL = "skill_manage"
SYNC_MODULE_NAME = "ai_badger_learned_skills_sync"


def hermes_skills_root() -> Path:
    """Resolve the Hermes skills root: HERMES_HOME wins, else the platform default."""
    override = os.environ.get("HERMES_HOME", "").strip()
    base = Path(override).expanduser() if override else Path.home() / ".hermes"
    return base / "skills"


def _load_learned_skills_sync() -> Optional[Any]:
    """Import the sibling sync module lazily; None when an older scaffold lacks it."""
    cached = sys.modules.get(SYNC_MODULE_NAME)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / "learned_skills_sync.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(SYNC_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[SYNC_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # pylint: disable=broad-exception-caught
        sys.modules.pop(SYNC_MODULE_NAME, None)
        logger.warning("learned-skill sync could not be loaded from %s", path, exc_info=True)
        return None
    return module


def _sync_learned_skill(args: Dict[str, Any], status: str, cwd: str) -> None:
    """Hand one skill_manage call to the sync.

    Hermes' post_tool_call payload carries no cwd, so the process cwd is the only
    project signal available; the sync itself no-ops unless it is a scaffolded project.
    """
    sync = _load_learned_skills_sync()
    if sync is None:
        return
    outcome = sync.on_skill_manage(
        args, status, cwd or os.getcwd(),
        skills_root=hermes_skills_root(),
        now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        tool_name=SKILL_MANAGE_TOOL,
    )
    if outcome:
        logger.debug("learned-skill sync: %s", outcome)


# ---------------------------------------------------------------------------
# Commit reminder — Hermes has no PostToolUse return channel into the model's
# context, so the check runs here and stashes a pending nudge that
# pre_llm_inject_context surfaces on the very next turn (docs: commit-reminder skill).
# ---------------------------------------------------------------------------

COMMIT_REMINDER_MODULE_NAME = "ai_badger_commit_reminder"
IMPACT_ESTIMATOR_MODULE_NAME = "ai_badger_impact_estimator"
COMMIT_REMINDER_THRESHOLD_ENV = "AI_BADGER_COMMIT_REMINDER_THRESHOLD"
COMMIT_REMINDER_IMPACT_ENV = "AI_BADGER_COMMIT_REMINDER_IMPACT"
DEFAULT_COMMIT_REMINDER_THRESHOLD = 5

# Deliberately separate from commit_reminder.py's own STATE_FILE (the per-project marker
# ratchet): a pending nudge is Hermes-only and clears the moment it is surfaced, a
# different lifecycle from the marker's threshold-crossing debounce. Keeping them apart
# means this addition can never corrupt the marker schema the Claude/Copilot hook depends on.
PENDING_REMINDER_FILE = Path.home() / ".ai-badger" / "commit-reminder" / "pending.json"


def _load_commit_reminder() -> Optional[Any]:
    """Import the sibling commit_reminder module lazily; None when an older scaffold lacks it."""
    cached = sys.modules.get(COMMIT_REMINDER_MODULE_NAME)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / "commit_reminder.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(COMMIT_REMINDER_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[COMMIT_REMINDER_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # pylint: disable=broad-exception-caught
        sys.modules.pop(COMMIT_REMINDER_MODULE_NAME, None)
        logger.warning("commit_reminder could not be loaded from %s", path, exc_info=True)
        return None
    return module


def _load_impact_estimator() -> Optional[Any]:
    """Import the sibling impact_estimator module lazily; None when an older scaffold lacks it."""
    cached = sys.modules.get(IMPACT_ESTIMATOR_MODULE_NAME)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / "impact_estimator.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(IMPACT_ESTIMATOR_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[IMPACT_ESTIMATOR_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # pylint: disable=broad-exception-caught
        sys.modules.pop(IMPACT_ESTIMATOR_MODULE_NAME, None)
        logger.warning("impact_estimator could not be loaded from %s", path, exc_info=True)
        return None
    return module


def _commit_reminder_threshold() -> int:
    """Read the threshold from env, guarded int-parse; default 5."""
    try:
        return int(os.environ.get(COMMIT_REMINDER_THRESHOLD_ENV, ""))
    except ValueError:
        return DEFAULT_COMMIT_REMINDER_THRESHOLD


def _load_pending_reminders() -> Dict[str, str]:
    """Load the pending-reminder file; `{}` on missing file, read error, or malformed JSON."""
    try:
        raw = PENDING_REMINDER_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_pending_reminders(pending: Dict[str, str]) -> None:
    """Persist the pending-reminder file, creating parent directories as needed."""
    PENDING_REMINDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_REMINDER_FILE.write_text(json.dumps(pending), encoding="utf-8")


def _set_pending_reminder(project: str, message: str) -> None:
    """Stash ``message`` for ``project``, keyed by its resolved absolute path."""
    pending = _load_pending_reminders()
    pending[str(Path(project).resolve())] = message
    _save_pending_reminders(pending)


def _pop_pending_reminder(project: str) -> Optional[str]:
    """Return and clear the pending reminder for ``project``, or None if there isn't one."""
    pending = _load_pending_reminders()
    key = str(Path(project).resolve())
    message = pending.pop(key, None)
    if message is not None:
        _save_pending_reminders(pending)
    return message


def _maybe_remind_commit(tool_name: str, cwd: str) -> None:
    """After an edit-shaped tool call, ratchet-check the uncommitted count and stash a nudge.

    Guard: an unavailable module or a non-edit tool name skips before any git call.
    """
    commit_reminder = _load_commit_reminder()
    if commit_reminder is None or not commit_reminder.is_edit_tool(tool_name):
        _debug("ai_badger_hooks/commit_reminder", "skip", tool_name=tool_name)
        return

    project = _project_cwd(cwd)
    files = commit_reminder.uncommitted_files(project)
    count = len(files)
    marker = commit_reminder.get_marker(project)
    threshold = _commit_reminder_threshold()
    _debug("ai_badger_hooks/commit_reminder", "checked", project=project,
           count=count, threshold=threshold)

    fires, new_marker = commit_reminder.should_remind(count, marker, threshold=threshold)
    commit_reminder.set_marker(project, new_marker)
    if not fires:
        return

    impact_estimator = _load_impact_estimator()
    if impact_estimator is not None:
        use_graph = os.environ.get(COMMIT_REMINDER_IMPACT_ENV) == "graph"
        impact = impact_estimator.estimate_impact(files, project, use_graph=use_graph)
    else:
        impact = f"{count} file(s) changed"
    message = f"[ai-badger] {impact}. Consider committing your work."
    _set_pending_reminder(project, message)
    _debug("ai_badger_hooks/commit_reminder", "fire", project=project,
           count=count, threshold=threshold)


# ---------------------------------------------------------------------------
# Tool call observer — equivalent to Claude's PostToolUse hook
# ---------------------------------------------------------------------------

def post_tool_observer(tool_name: str = "", result: str = "",
                        duration_ms: int = 0, cwd: str = "", **kwargs: Any) -> None:
    """Observe tool calls for debugging and metrics.

    Fires after every tool execution. Logs at DEBUG level so it doesn't flood
    the console. Enable by setting LOG_LEVEL=DEBUG on the ai_badger_hooks logger.
    """
    logger.debug(
        "tool=%s duration_ms=%d result_len=%d",
        tool_name, duration_ms, len(result) if result else 0,
    )

    if tool_name == SKILL_MANAGE_TOOL:
        try:
            _sync_learned_skill(kwargs.get("args") or {}, kwargs.get("status", "ok"), cwd)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("learned-skill sync failed", exc_info=True)

    try:
        _maybe_remind_commit(tool_name, cwd)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning("commit reminder check failed", exc_info=True)

    # Log index hit/miss metrics if the index is available
    if tool_name:
        project = _project_cwd(cwd)
        index = _load_mcp_index(project)
        if index:
            # Check if this tool exists in the index
            sname, _, tname = tool_name.partition(":") if ":" in tool_name else ("", "", tool_name)
            if not sname:
                sname = tool_name
            for server in index.get("sources", []):
                if server["name"] == sname:
                    known = tname in server.get("tools", {}) if tname else False
                    _debug(_MCP_RETRIEVAL_COMPONENT, "known" if known else "unknown",
                           project=project, **{_KEY_TOOL: tool_name})
                    break


# ---------------------------------------------------------------------------
# Plugin entry point — called by Hermes plugin loader
# ---------------------------------------------------------------------------

def register(ctx: Any) -> None:
    """Register all ai-badger hooks with the Hermes plugin system.

    The `ctx` object provides ctx.register_hook(name, callback).
    All callbacks accept **kwargs for forward compatibility — new
    parameters added in future Hermes versions won't break this plugin.

    Stale copies register nothing: the plugin still loads, so the session is unaffected, and
    the agent runs with ai-badger's hooks absent rather than wrong.
    """
    if COPY_SKEW_REFUSAL:
        print(f"ai-badger: hooks not registered — {COPY_SKEW_REFUSAL}", file=sys.stderr)
        logger.warning("ai-badger hooks not registered: %s", COPY_SKEW_REFUSAL)
        return
    ctx.register_hook("on_session_start", on_session_start_drift_notice)
    ctx.register_hook("pre_llm_call", pre_llm_inject_context)
    ctx.register_hook("post_tool_call", post_tool_observer)
    logger.info("ai-badger hooks registered: on_session_start, pre_llm_call, post_tool_call")

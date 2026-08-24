#!/usr/bin/env python3
"""One-shot S-D helper: create dotnet-workload gateway, git mv the 11 members under it."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import badger_lib as bl  # noqa: E402

STACK = ROOT / "features" / "dotnet" / "skills"
GATEWAY = STACK / "dotnet-workload"
MEMBERS = [
    ("dotnet-bdd-testing",
     ["bdd", "gherkin", "reqnroll", "feature file", "specflow", "xunit.v3", "scenario"]),
    ("dotnet-domain-modeling",
     ["domain model", "sealed record", "ddd", "aggregate", "value object", "guard clause",
      "fluentvalidation", "archunitnet", "domain purity"]),
    ("dotnet-flaky-test-diagnosis",
     ["flaky test", "passes alone", "intermittent test", "disableparallelization",
      "test race", "cold worktree"]),
    ("dotnet-hosted-service-review",
     ["backgroundservice", "ihostedservice", "hosted service review", "executeasync",
      "periodictimer", "poll loop", "watcher"]),
    ("dotnet-hosted-service-testing",
     ["faketimeprovider", "timeprovider", "hosted service test", "timer callback",
      "advance", "tick"]),
    ("dotnet-logger-message-design",
     ["loggermessage", "eventid", "fakelogger", "log assertion", "structured log design"]),
    ("dotnet-mcp-server",
     ["mcp", "model context protocol", "mcservertool", "stdio", "streamable http",
      "mcp tool"]),
    ("dotnet-sqlcipher-encryption",
     ["sqlcipher", "sqlite encryption", "e_sqlite3mc", "rekey", "database key",
      "sqlitepclraw"]),
    ("dotnet-system-commandline",
     ["system.commandline", "cli parsing", "command line arguments", "option validator",
      "fromamong"]),
    ("dotnet-tool-publishing",
     ["packastool", "nuget publish", "dotnet tool", "trusted publishing", "multi-rid",
      "msb3030", "toolcommandname"]),
    ("observability-contract-review",
     ["observability", "instrumentation review", "span", "metrics", "activity status",
      "opentelemetry"]),
]

assert not GATEWAY.exists(), "dotnet-workload already exists"

(GATEWAY / "references").mkdir(parents=True)
for name, _ in MEMBERS:
    subprocess.run(["git", "mv", name, f"dotnet-workload/references/{name}"],
                   cwd=STACK, check=True)

members = []
for name, triggers in MEMBERS:
    desc = bl.skill_description(GATEWAY / "references" / name / "SKILL.md")
    assert desc and desc.startswith("Use when"), name
    members.append({
        "name": name,
        "purpose": desc,
        "triggers": triggers,
        "paths": {"skill": f"references/{name}"},
    })

manifest = {"kind": "gateway", "members": members}
(GATEWAY / "manifest.json").write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("moved", len(members), "members; manifest written")

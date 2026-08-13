#!/usr/bin/env python3
"""Convert MCP catalog meta.json prerequisite declarations to include structured local/global options.

Converts Python-based and .NET-based MCP catalog entries to include:
  - local {}
  - global {}
  - uv commands for Python packages
  - dotnet tool local / global commands for .NET packages
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONVERSIONS = {
    "semantica": {
        "local": {
            "summary": "Local virtual environment (.venv) using uv or python -m venv",
            "check": "python3 features/common/mcp/semantica/scripts/check.py",
            "install": "python3 features/common/mcp/semantica/scripts/install.py",
            "uv": "uv venv .venv && uv pip install semantica",
            "command": "python3 features/common/mcp/semantica/scripts/install.py --target ."
        },
        "global": {
            "summary": "Global user-scoped tool install via uv tool install or pipx",
            "check": "semantica --version",
            "install": "uv tool install semantica",
            "uv": "uv tool install semantica",
            "command": "uv tool install semantica"
        }
    },
    "code-review-graph": {
        "local": {
            "summary": "Local virtual environment (.venv) using uv or python -m venv",
            "check": "python3 features/common/mcp/code-review-graph/scripts/check.py",
            "install": "python3 features/common/mcp/code-review-graph/scripts/install.py",
            "uv": "uv venv .venv && uv pip install code-review-graph",
            "command": "python3 features/common/mcp/code-review-graph/scripts/install.py --target ."
        },
        "global": {
            "summary": "Global user-scoped tool install via uv tool install or pipx",
            "check": "code-review-graph --version",
            "install": "uv tool install code-review-graph",
            "uv": "uv tool install code-review-graph",
            "command": "uv tool install code-review-graph"
        }
    },
    "ai-raccoon": {
        "local": {
            "summary": "Local .NET tool manifest installation",
            "check": "dotnet tool run ai-raccoon --version",
            "install": "dotnet tool install ai-raccoon --local",
            "command": "dotnet tool install ai-raccoon --local"
        },
        "global": {
            "summary": "Global .NET tool installation",
            "check": "ai-raccoon --version",
            "install": "dotnet tool install -g ai-raccoon",
            "command": "dotnet tool install -g ai-raccoon"
        }
    },
    "hermes": {
        "local": {
            "summary": "Hermes Agent CLI in local project environment",
            "check": "hermes --version",
            "install": "pip install hermes-agent",
            "uv": "uv tool install hermes-agent",
            "command": "pip install hermes-agent"
        },
        "global": {
            "summary": "Global Hermes Agent CLI installation",
            "check": "hermes --version",
            "install": "https://hermes-agent.nousresearch.com/docs/getting-started/installation",
            "uv": "uv tool install hermes-agent",
            "command": "uv tool install hermes-agent"
        }
    },
    "aspire": {
        "local": {
            "summary": "Local Aspire CLI apphost integration",
            "check": "aspire --version",
            "install": "https://aspire.dev/get-started/install-cli/",
            "command": "aspire agent mcp"
        },
        "global": {
            "summary": "Global Aspire CLI installation",
            "check": "aspire --version",
            "install": "https://aspire.dev/get-started/install-cli/",
            "command": "aspire agent mcp"
        }
    }
}

def main() -> int:
    converted = 0
    for meta_path in ROOT.glob("features/**/mcp/*/meta.json"):
        server_name = meta_path.parent.name
        if server_name not in CONVERSIONS:
            continue
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        prereq = data.get("prerequisite", {})
        config = CONVERSIONS[server_name]
        prereq["local"] = config["local"]
        prereq["global"] = config["global"]
        data["prerequisite"] = prereq
        meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"Converted {server_name}: {meta_path.relative_to(ROOT)}")
        converted += 1
    print(f"Successfully converted {converted} meta.json catalog entry/entries.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

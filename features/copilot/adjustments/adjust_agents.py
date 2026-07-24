"""Adjustment: map ai-badger personas to Copilot custom agents.

Copilot discovers custom agents from .github/agents/*.agent.md with YAML
frontmatter. This adjustment converts ai-badger personas into Copilot
custom agent format.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


# Map persona names to Copilot agent descriptions and tool access
PERSONA_MAP = {
    "architect": {
        "description": "System architecture and design decisions. Reviews patterns, evaluates trade-offs, and proposes structural improvements.",
        "tools": ["read", "search", "list_files"],
        "user-invocable": True,
    },
    "code-reviewer": {
        "description": "Code review with focus on quality, security, and maintainability. Reviews diffs, identifies issues, and suggests improvements.",
        "tools": ["read", "search", "list_files", "get_diff"],
        "user-invocable": True,
    },
    "test-engineer": {
        "description": "Test strategy and implementation. Writes failing tests first, implements to pass, and ensures coverage.",
        "tools": ["read", "search", "list_files", "run_command"],
        "user-invocable": True,
    },
}


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Convert personas to Copilot custom agents.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
            'index': dict,
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    if "copilot" not in context.get("config", {}).get("agents", []):
        return {"applied": False, "files": [], "notes": "copilot not in config.agents"}

    framework_root = context["framework_root"]
    target = context["target"]
    index = context.get("index", {})

    # Find persona files in the index
    personas: List[Dict[str, Any]] = []
    for stack_name, stack_data in index.get("stacks", {}).items():
        for persona in stack_data.get("personas", []):
            personas.append(persona)

    if not personas:
        return {"applied": False, "files": [], "notes": "No personas found in index"}

    agents_dir = target / ".github" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    created = []
    for persona in personas:
        name = persona.get("name", "")
        persona_path = framework_root / persona.get("path", "")

        if not persona_path.exists():
            continue

        # Read persona content
        persona_content = persona_path.read_text(encoding="utf-8")

        # Get agent config from map or use defaults
        agent_config = PERSONA_MAP.get(name, {
            "description": f"AI agent persona: {name}",
            "tools": ["read", "search"],
            "user-invocable": True,
        })

        # Generate Copilot custom agent format
        agent_md = f"""---
name: {name}
description: {agent_config['description']}
tools:
{chr(10).join(f'  - {t}' for t in agent_config['tools'])}
user-invocable: {str(agent_config['user-invocable']).lower()}
---

{persona_content}
"""
        agent_file = agents_dir / f"{name}.agent.md"
        agent_file.write_text(agent_md, encoding="utf-8")
        created.append(name)

    if created:
        return {
            "applied": True,
            "files": [f".github/agents/{name}.agent.md" for name in created],
            "notes": f"Created {len(created)} Copilot custom agent(s) from personas",
        }
    return {"applied": False, "files": [], "notes": "No persona files found to convert"}

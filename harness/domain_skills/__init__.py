"""Friday AI — Domain Skill Registry.

Auto-discovers and indexes domain skill markdown files from the
domain_skills/ directory tree. Provides lookup, search, and bulk
registration with the RuntimeHarness orchestrator.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from ..models import ToolDef

_DOMAIN_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))


class DomainSkillRegistry:
    """Scans, indexes, and serves domain skills for the harness."""

    def __init__(self) -> None:
        self._skills: Dict[str, List[Dict[str, Any]]] = {}
        self._domain_metadata: Dict[str, Dict[str, Any]] = {}
        self._scan()

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def domains(self) -> List[str]:
        """Return sorted list of registered domain names."""
        return sorted(self._skills.keys())

    @property
    def total_skills(self) -> int:
        """Return total number of individual skill documents."""
        return sum(len(v) for v in self._skills.values())

    def get_domain_skills(self, domain: str) -> List[Dict[str, Any]]:
        """Return all skill entries for a domain."""
        return self._skills.get(domain, [])

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search across all skill descriptions and titles."""
        q = query.lower()
        results: List[Dict[str, Any]] = []
        for domain, skills in self._skills.items():
            for s in skills:
                if q in s["title"].lower() or q in s["domain"]:
                    results.append(s)
        return results

    def get_domain_summary(self, domain: str) -> Optional[Dict[str, Any]]:
        """Return summary metadata for a domain."""
        return self._domain_metadata.get(domain)

    def summaries(self) -> List[Dict[str, Any]]:
        """Return a concise summary list of all registered skills."""
        out: List[Dict[str, Any]] = []
        for domain, skills in self._skills.items():
            for s in skills:
                out.append({
                    "domain": domain,
                    "title": s["title"],
                    "file": os.path.basename(s["path"]),
                    "workflows": s["workflows"],
                })
        return sorted(out, key=lambda x: (x["domain"], x["title"]))

    def register_all(
        self,
        register_fn,
        category: str = "domain_skill",
    ) -> List[ToolDef]:
        """Register all domain skills as tools via a callback.

        Args:
            register_fn: A callable with signature
                (name, description, handler, category) -> ToolDef.
                Typically ``orchestrator.register_tool``.
            category: Tool category label.

        Returns:
            List of registered ToolDef instances.
        """
        tool_defs: List[ToolDef] = []
        for domain, skills in self._skills.items():
            for s in skills:
                tool_name = f"{domain}_{os.path.splitext(os.path.basename(s['path']))[0]}"
                # Build a concise description from the first workflow line
                wf = s["workflows"]
                desc = s["title"]
                if wf:
                    desc += f" — {wf[0]}"

                def _make_handler(skill_info: Dict[str, Any]) -> callable:
                    """Closure to capture skill info."""
                    def _handler(**kwargs: Any) -> Dict[str, Any]:
                        return {
                            "domain": skill_info["domain"],
                            "title": skill_info["title"],
                            "workflows": skill_info["workflows"],
                            "gotchas": skill_info["gotchas"],
                            "primitives": skill_info["primitives"],
                            "file": skill_info["path"],
                        }
                    return _handler

                td = register_fn(
                    name=tool_name,
                    description=desc,
                    handler=_make_handler(s),
                    category=category,
                )
                tool_defs.append(td)
        return tool_defs

    # ── Internal ─────────────────────────────────────────────────────────────

    def _scan(self) -> None:
        """Walk domain_skills/ and index all markdown files."""
        if not os.path.isdir(_DOMAIN_SKILLS_DIR):
            return

        for entry in sorted(os.listdir(_DOMAIN_SKILLS_DIR)):
            domain_path = os.path.join(_DOMAIN_SKILLS_DIR, entry)
            if not os.path.isdir(domain_path) or entry.startswith("_"):
                continue

            md_files = sorted(
                f for f in os.listdir(domain_path) if f.endswith(".md")
            )
            if not md_files:
                continue

            domain_name = entry
            domain_skills: List[Dict[str, Any]] = []

            for md_file in md_files:
                md_path = os.path.join(domain_path, md_file)
                info = self._parse_markdown(md_path, domain_name)
                if info:
                    domain_skills.append(info)

            if domain_skills:
                self._skills[domain_name] = domain_skills
                self._domain_metadata[domain_name] = {
                    "path": domain_path,
                    "files": len(md_files),
                    "skills": len(domain_skills),
                }

    def _parse_markdown(
        self, path: str, domain: str
    ) -> Optional[Dict[str, Any]]:
        """Extract title, workflows, gotchas, and primitives from a skill MD."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return None

        # Title: first H1
        title = domain
        m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if m:
            title = m.group(1).strip()

        # Sections
        workflows = self._extract_section(content, "Common workflows")
        gotchas = self._extract_section(content, "Gotchas")

        # Detect primitives used in code blocks
        primitives = set()
        for prim in ("http_get", "goto_url", "wait_for_load", "js", "wait"):
            if prim in content:
                primitives.add(prim)

        return {
            "domain": domain,
            "title": title,
            "path": path,
            "workflows": workflows,
            "gotchas": gotchas,
            "primitives": sorted(primitives),
            "content_preview": content[:500],
        }

    @staticmethod
    def _extract_section(content: str, section_title: str) -> List[str]:
        """Extract bullet-point lines under a ## section heading."""
        pattern = rf"^##\s+{re.escape(section_title)}\s*$(.+?)(?=^##\s|\Z)"
        m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if not m:
            return []
        block = m.group(1).strip()
        # Grab bullet lines
        lines = re.findall(r"^- \*\*(.+?)\*\*", block)
        if not lines:
            lines = re.findall(r"^- (.+)$", block, re.MULTILINE)
        return [ln.strip() for ln in lines[:10]]


# Module-level singleton for convenience
_registry: Optional[DomainSkillRegistry] = None


def get_registry() -> DomainSkillRegistry:
    """Get or create the global DomainSkillRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = DomainSkillRegistry()
    return _registry

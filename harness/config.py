"""Friday AI Runtime Harness — Configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class HarnessConfig:
    """Central configuration for the runtime harness."""

    # ── Model Settings ───────────────────────────────────────────────────────
    primary_model: str = os.getenv("PRIMARY_MODEL", "deepseek-ai/deepseek-v4-pro")
    vision_model: str = os.getenv("VISION_MODEL", "meta/llama-3.2-11b-vision-instruct")
    fallback_models: List[str] = field(default_factory=lambda: [
        "deepseek-ai/deepseek-v3",
        "nvidia/llama-3.1-nemotron-70b-instruct",
    ])
    nvidia_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("NVIDIA_API_KEY") or os.getenv("NVIDIA_API_KEY")
    )
    api_base_url: str = os.getenv("API_BASE_URL", "https://integrate.api.nvidia.com/v1")

    # ── Execution Settings ───────────────────────────────────────────────────
    max_steps_per_plan: int = 25
    max_concurrent_tools: int = 3
    tool_timeout_default: int = 30
    max_retries_per_tool: int = 3
    retry_delay_base: float = 1.0

    # ── Context Management ───────────────────────────────────────────────────
    max_context_tokens: int = 32000
    context_compression_threshold: int = 28000
    max_history_messages: int = 50
    enable_context_compression: bool = True

    # ── Memory Settings ──────────────────────────────────────────────────────
    memory_db_path: str = os.getenv("MEMORY_DB_PATH", "data/memory.db")
    enable_memory: bool = True
    memory_importance_threshold: float = 0.3

    # ── Security ─────────────────────────────────────────────────────────────
    dangerous_tool_confirm: bool = True
    shell_safety_filter: bool = True
    allowed_paths: List[str] = field(default_factory=lambda: [
        os.getcwd(),
        os.path.expanduser("~"),
    ])
    blocked_commands: List[str] = field(default_factory=lambda: [
        "rm -rf /", "sudo", "chmod 777", "dd if=", "mkfs",
        "> /dev/", ":(){ :|:& };:", "wget http://", "curl http://",
    ])

    # ── Observability ────────────────────────────────────────────────────────
    enable_tracing: bool = True
    enable_metrics: bool = True
    log_level: str = os.getenv("HARNESS_LOG_LEVEL", "INFO")
    cost_per_1k_input: float = 0.0005
    cost_per_1k_output: float = 0.0015

    # ── Extensions ───────────────────────────────────────────────────────────
    plugin_dir: str = "plugins"
    enable_plugins: bool = True
    auto_load_plugins: bool = True

    # ── Research Mode ────────────────────────────────────────────────────────
    max_search_results: int = 5
    max_sources_per_research: int = 10
    research_timeout: int = 60

    # ── Integration ──────────────────────────────────────────────────────────
    use_existing_brain: bool = True
    use_existing_executive: bool = True
    use_existing_mcp: bool = True
    harness_enabled: bool = True


# Global singleton
_global_config: Optional[HarnessConfig] = None


def get_config() -> HarnessConfig:
    """Get the global harness configuration, creating it if needed."""
    global _global_config
    if _global_config is None:
        _global_config = HarnessConfig()
    return _global_config


def set_config(config: HarnessConfig) -> None:
    """Set the global harness configuration."""
    global _global_config
    _global_config = config

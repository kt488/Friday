"""
Configuration management for EVA evaluation harness.

Thread-safe singleton with YAML loading and environment variable overrides.
"""

import os
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


class EVAConfigError(Exception):
    """Raised when configuration is invalid or cannot be loaded."""


class EVAConfig:
    """Thread-safe configuration singleton with env override support.

    Usage:
        EVAConfig.load("path/to/config.yaml")
        val = EVAConfig.get("engine.max_workers", default=4)
        section = EVAConfig.get_section("engine")
    """

    _instance: Optional["EVAConfig"] = None
    _lock = threading.Lock()
    _config: Dict[str, Any] = {}
    _config_path: Optional[Path] = None

    def __new__(cls) -> "EVAConfig":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def load(cls, path: Optional[str] = None) -> Dict[str, Any]:
        """Load configuration from YAML file.

        Args:
            path: Path to YAML config file. Defaults to eva/config.yaml.

        Returns:
            Loaded configuration dictionary.

        Raises:
            EVAConfigError: If config file not found or invalid.
        """
        with cls._lock:
            config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
            if not config_path.exists():
                raise EVAConfigError(f"Config file not found: {config_path}")

            with open(config_path, "r") as f:
                cls._config = yaml.safe_load(f) or {}

            cls._config_path = config_path
            cls._apply_env_overrides()
            cls._validate()
            logger.info("Configuration loaded from %s", config_path)
            return cls._config

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get config value by dot-notation key.

        Args:
            key: Dot-separated key path (e.g., 'engine.max_workers').
            default: Default value if key not found.

        Returns:
            Config value or default.
        """
        parts = key.split(".")
        value = cls._config
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return default
        return value if value is not None else default

    @classmethod
    def get_section(cls, section: str) -> Dict[str, Any]:
        """Get entire config section.

        Args:
            section: Section name.

        Returns:
            Dict of section config values.
        """
        return cls._config.get(section, {})

    @classmethod
    def set_section(cls, section: str, values: Dict[str, Any]) -> None:
        """Set an entire config section (thread-safe).

        Args:
            section: Section name.
            values: Dict of config values for the section.
        """
        with cls._lock:
            cls._config[section] = values

    @classmethod
    def reload(cls) -> Dict[str, Any]:
        """Reload configuration from file.

        Returns:
            Reloaded configuration dict.
        """
        if cls._config_path:
            return cls.load(str(cls._config_path))
        return cls.load()

    @classmethod
    def _apply_env_overrides(cls) -> None:
        """Override config values from EVA_* environment variables.

        Environment variables use double-underscore as separator.
        E.g., EVA_ENGINE_MAX_WORKERS=8 sets engine.max_workers.
        """
        prefix = "EVA_"
        for env_key, env_val in os.environ.items():
            if not env_key.startswith(prefix):
                continue

            path = env_key[len(prefix):].lower().replace("__", ".")
            parts = path.split(".")

            target = cls._config
            for part in parts[:-1]:
                if part not in target:
                    target[part] = {}
                target = target[part]

            key = parts[-1]
            if not isinstance(target, dict):
                logger.warning("Cannot set env override %s: path conflicts with value", env_key)
                continue

            typed_val: Any = env_val
            if env_val.lower() in ("true", "yes", "1"):
                typed_val = True
            elif env_val.lower() in ("false", "no", "0"):
                typed_val = False
            elif env_val.isdigit():
                typed_val = int(env_val)
            else:
                try:
                    typed_val = float(env_val)
                except ValueError:
                    pass

            target[key] = typed_val

    @classmethod
    def _validate(cls) -> bool:
        """Validate config has required sections.

        Returns:
            True if valid.

        Raises:
            EVAConfigError: If required sections are missing.
        """
        required_sections = ["general", "engine"]
        for section in required_sections:
            if section not in cls._config:
                msg = f"Missing required config section: '{section}'"
                logger.warning(msg)

        engine = cls._config.get("engine", {})
        if engine.get("default_timeout", 0) <= 0:
            logger.warning("engine.default_timeout must be positive, using default 60")
            engine["default_timeout"] = 60

        return True

    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
        """Return a copy of the full configuration.

        Returns:
            Deep copy of config dict.
        """
        return json.loads(json.dumps(cls._config))

    @classmethod
    def reset(cls) -> None:
        """Reset configuration to empty (for testing)."""
        with cls._lock:
            cls._config = {}
            cls._config_path = None

"""
EVA - Evaluation & Verification Agent for Friday AI
=====================================================

Production-grade AI Evaluation & Testing Harness designed to
continuously evaluate, benchmark, stress test, monitor, and
improve Friday AI.

Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "Friday AI"
__description__ = "AI Evaluation & Testing Harness"

import logging
from typing import Dict, List, Optional

from eva.core.registry import PluginRegistry
from eva.config import EVAConfig

logger = logging.getLogger(__name__)


def init(config_path: Optional[str] = None) -> None:
    """Initialize EVA with optional config path.

    Args:
        config_path: Path to YAML configuration file.
    """
    EVAConfig.load(config_path)
    count = PluginRegistry.discover("eva")
    logger.info("EVA initialized. Discovered %d plugins.", count)

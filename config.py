"""Centralized configuration for the AIGC Creative Workflow."""

import os
import sys
import logging

from dotenv import load_dotenv

load_dotenv()

# --- Model Configuration ---
LLM_MODEL = os.getenv("AIGC_LLM_MODEL", "claude-sonnet-4-20250514")
IMAGE_MODEL = os.getenv("AIGC_IMAGE_MODEL", "gemini-3-pro-image-preview")

# --- LLM Sampling ---
_temp_env = os.getenv("AIGC_LLM_TEMPERATURE", "")
LLM_TEMPERATURE: float | None = float(_temp_env) if _temp_env else None  # None = API default

# --- API Retry ---
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds

# --- Logging ---
LOG_LEVEL = os.getenv("AIGC_LOG_LEVEL", "INFO")


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("aigc")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
        ))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    return logger


def check_api_keys():
    """Validate required API keys are set. Exit early with clear message if missing."""
    missing = []
    if not os.getenv("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if not os.getenv("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    if missing:
        print(f"\n[ERROR] 缺少必需的环境变量: {', '.join(missing)}")
        print("请在 .env 文件或系统环境变量中设置后重试。")
        sys.exit(1)


logger = setup_logging()

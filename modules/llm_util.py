"""Shared LLM utilities: call_llm() and parse_json_array()."""

import json
import re
import time

import anthropic

from config import LLM_MODEL, MAX_RETRIES, RETRY_BASE_DELAY, logger

SYSTEM_PROMPT = "你是一个创意营销助手。请严格按照用户要求的 JSON 格式输出，不要添加任何 markdown 标记或额外说明文字。只输出纯 JSON。"


def call_llm(user_content: str, *, max_tokens: int = 4096) -> str:
    """Call Claude API with retry logic and a system prompt that constrains JSON output."""
    client = anthropic.Anthropic()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=LLM_MODEL,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            return response.content[0].text
        except anthropic.APIError as e:
            if attempt == MAX_RETRIES:
                raise
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(f"API 调用失败 (尝试 {attempt}/{MAX_RETRIES}): {e}，{delay}s 后重试")
            time.sleep(delay)
    raise RuntimeError(f"LLM 调用在 {MAX_RETRIES} 次重试后仍然失败")


def parse_json_array(text: str) -> list[dict]:
    """Parse a JSON array from LLM output, stripping markdown code fences if present."""
    # Remove markdown code fences (```json ... ``` or ``` ... ```)
    cleaned = re.sub(r"```(?:json)?\s*\n?", "", text).strip()
    cleaned = cleaned.rstrip("`").strip()

    start = cleaned.find("[")
    end = cleaned.rfind("]") + 1
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法从 LLM 响应中解析 JSON: {text[:200]}")

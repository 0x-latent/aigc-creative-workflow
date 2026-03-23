"""Shared LLM utilities: call_llm() and parse_json_array()."""

import json
import re
import time

import anthropic

from config import LLM_MODEL, MAX_RETRIES, RETRY_BASE_DELAY, logger

SYSTEM_PROMPT = (
    "你是一个创意营销助手。请严格按照用户要求的 JSON 格式输出。"
    "规则：1) 直接输出 JSON 数组，不要添加 markdown 标记、代码围栏或任何说明文字；"
    "2) JSON 字符串值中不允许出现未转义的换行符，必须使用 \\n 表示；"
    "3) 确保 JSON 语法完全正确，可被 json.loads 直接解析。"
)


def call_llm(user_content: str, *, max_tokens: int = 4096) -> str:
    """Call Claude API with retry logic, prefilled assistant response for reliable JSON."""
    client = anthropic.Anthropic()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=LLM_MODEL,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": "["},
                ],
            )
            if response.stop_reason == "max_tokens":
                logger.warning(f"LLM 输出被截断（已用满 {max_tokens} tokens），将尝试修复")
            raw = response.content[0].text
            # Prepend the "[" we prefilled, but avoid duplication if LLM echoed it
            if raw.lstrip().startswith("["):
                return raw
            return "[" + raw
        except anthropic.APIError as e:
            if attempt == MAX_RETRIES:
                raise
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(f"API 调用失败 (尝试 {attempt}/{MAX_RETRIES}): {e}，{delay}s 后重试")
            time.sleep(delay)
    raise RuntimeError(f"LLM 调用在 {MAX_RETRIES} 次重试后仍然失败")


def _fix_json_strings(text: str) -> str:
    """Fix common LLM JSON issues: unescaped control characters inside string values."""
    # Replace literal control characters (newlines, tabs, etc.) inside JSON strings
    # with their escaped equivalents. We track whether we're inside a string.
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string:
            if ch == '\n':
                result.append('\\n')
            elif ch == '\r':
                result.append('\\r')
            elif ch == '\t':
                result.append('\\t')
            elif ord(ch) < 0x20:
                result.append(f'\\u{ord(ch):04x}')
            else:
                result.append(ch)
        else:
            result.append(ch)
    return ''.join(result)


def parse_json_array(text: str) -> list[dict]:
    """Parse a JSON array from LLM output, stripping markdown code fences if present.

    Handles: markdown fences, unescaped control characters in strings, truncated JSON.
    """
    from config import logger

    # Remove markdown code fences (```json ... ``` or ``` ... ```)
    cleaned = re.sub(r"```(?:json)?\s*\n?", "", text).strip()
    cleaned = cleaned.rstrip("`").strip()

    start = cleaned.find("[")
    if start == -1:
        raise ValueError(f"无法从 LLM 响应中解析 JSON: {text[:200]}")

    end = cleaned.rfind("]") + 1
    if end > start:
        json_str = cleaned[start:end]
        # Try direct parse first
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        # Fix control characters in string values and retry
        try:
            fixed = _fix_json_strings(json_str)
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败（修复控制字符后仍然失败）: {e}")

    # JSON appears truncated — attempt repair
    fragment = cleaned[start:]
    fragment_fixed = _fix_json_strings(fragment)
    logger.warning(f"LLM 响应的 JSON 需要修复（总长 {len(fragment)} 字符），尝试截断修复...")
    repaired = _repair_truncated_json(fragment_fixed)
    if repaired is not None:
        logger.info(f"JSON 修复成功，解析到 {len(repaired)} 个完整元素")
        return repaired

    logger.error(f"JSON 修复失败。开头: {fragment[:200]}... 末尾: ...{fragment[-100:]}")
    raise ValueError(f"LLM 输出的 JSON 无法解析。请重试。")


def _repair_truncated_json(fragment: str) -> list[dict] | None:
    """Try to repair truncated JSON array by closing open structures."""
    # Strategy 1: truncate to last complete object in array, then close
    # Find the last complete "}," or "}" that closes a top-level array element
    depth_brace = 0
    depth_bracket = 0
    in_string = False
    escape_next = False
    last_complete_obj_end = -1

    for i, ch in enumerate(fragment):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == '{':
            depth_brace += 1
        elif ch == '}':
            depth_brace -= 1
            if depth_brace == 0 and depth_bracket == 1:
                last_complete_obj_end = i
        elif ch == '[':
            depth_bracket += 1
        elif ch == ']':
            depth_bracket -= 1

    if last_complete_obj_end > 0:
        candidate = fragment[:last_complete_obj_end + 1] + "]"
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None

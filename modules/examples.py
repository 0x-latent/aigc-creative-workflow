"""ExamplesLoader — load few-shot examples from brands/{id}/examples/ for prompt injection."""

import json
import os

from config import logger

MAX_EXAMPLES = 3


class ExamplesLoader:
    def load(self, brand_id: str, step: str, brands_dir: str = "brands") -> str:
        """Load examples for a given step (concept/direction/script).

        Looks for JSON files in brands/{brand_id}/examples/{step}/.
        Returns formatted text suitable for injection into prompts,
        or empty string if no examples found.
        """
        examples_dir = os.path.join(brands_dir, brand_id, "examples", step)
        if not os.path.isdir(examples_dir):
            return ""

        examples = []
        for fname in sorted(os.listdir(examples_dir)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(examples_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                examples.append(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"跳过无效示例文件 {fpath}: {e}")
                continue
            if len(examples) >= MAX_EXAMPLES:
                break

        if not examples:
            return ""

        lines = ["\n\n--- 参考示例（仅供风格参考，不要直接复制）---"]
        for i, ex in enumerate(examples, 1):
            lines.append(f"\n示例 {i}:")
            lines.append(json.dumps(ex, ensure_ascii=False, indent=2))
        lines.append("\n--- 示例结束 ---\n")

        logger.info(f"  加载了 {len(examples)} 个 {step} 参考示例")
        return "\n".join(lines)

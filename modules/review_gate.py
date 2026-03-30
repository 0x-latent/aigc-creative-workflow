import sys
from datetime import datetime, timezone
from models.base import ReviewDecision

_FEEDBACK_DIMS = {
    1: "调性/风格",
    2: "视觉表现",
    3: "受众匹配",
    4: "平台适配",
    5: "品牌一致性",
    6: "其他",
}


def _collect_structured_feedback() -> str:
    """Collect structured feedback: dimension selection + free-form detail."""
    print("  选择需要改进的维度（可多选，逗号分隔，直接回车跳过）:")
    print("    1. 调性/风格  2. 视觉表现  3. 受众匹配  4. 平台适配  5. 品牌一致性  6. 其他")
    dims_input = input("  维度: ").strip()
    detail = input("  具体修改方向: ").strip()

    if dims_input:
        selected = [
            _FEEDBACK_DIMS[int(d.strip())]
            for d in dims_input.split(",")
            if d.strip().isdigit() and int(d.strip()) in _FEEDBACK_DIMS
        ]
        if selected:
            return f"需改进维度: {', '.join(selected)}。{detail}"
    return detail


class ReviewGate:
    def review_list(self, items: list[dict], step_name: str) -> ReviewDecision:
        """Display items and let user choose one, reject all, merge, or quit.

        Args:
            items: list of dicts with at least 'id' and 'title' keys
            step_name: name of current workflow step for display
        """
        print(f"\n{'='*60}")
        print(f"  审核环节: {step_name}")
        print(f"{'='*60}")

        for i, item in enumerate(items, 1):
            print(f"\n  [{i}] {item.get('title', item.get('id', ''))}")
            if "description" in item:
                print(f"      {item['description']}")
            if "rationale" in item:
                print(f"      推导依据: {item['rationale']}")
            if "platform_notes" in item:
                print(f"      平台适配: {item['platform_notes']}")
            if "outline" in item:
                print(f"      大纲: {item['outline']}")
            if "scenes" in item:
                for s in item["scenes"]:
                    print(f"        场景{s['scene_no']}: {s['visual_description']}")
                    print(f"          旁白: {s['voiceover']}")

        print(f"\n{'─'*60}")
        print("  输入数字选择并通过（多选用逗号分隔，如 1,3）")
        print("  输入 m 混合多个方案，输入 r 打回重新生成，输入 q 退出工作流")
        print(f"{'─'*60}")

        while True:
            choice = input("  请输入: ").strip()
            if choice.lower() == "q":
                print("  工作流已退出。")
                sys.exit(0)

            if choice.lower() == "r":
                feedback = _collect_structured_feedback()
                return ReviewDecision(
                    status="rejected",
                    feedback=feedback,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if choice.lower() == "m":
                indices_str = input("  选择要混合的方案（如 1,3）: ").strip()
                try:
                    indices = [int(x.strip()) for x in indices_str.split(",")]
                    if not all(1 <= idx <= len(items) for idx in indices):
                        print(f"  请输入 1-{len(items)} 之间的数字")
                        continue
                    if len(indices) < 2:
                        print("  混合至少需要选择 2 个方案")
                        continue
                except ValueError:
                    print("  无效输入，请重试")
                    continue

                instruction = input("  混合指令（如：用方案1的调性+方案3的视觉）: ").strip()
                zero_based = [idx - 1 for idx in indices]
                return ReviewDecision(
                    status="merge",
                    feedback=instruction,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    selected_indices=zero_based,
                )

            try:
                indices = [int(x.strip()) for x in choice.split(",")]
                if all(1 <= idx <= len(items) for idx in indices):
                    zero_based = [idx - 1 for idx in indices]
                    return ReviewDecision(
                        status="approved",
                        feedback="",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        selected_index=zero_based[0],
                        selected_indices=zero_based,
                    )
                print(f"  请输入 1-{len(items)} 之间的数字")
            except ValueError:
                print("  无效输入，请重试")

    def review_images(self, image_paths: list[str]) -> ReviewDecision:
        """Review generated images."""
        print(f"\n{'='*60}")
        print("  审核环节: 生成图片")
        print(f"{'='*60}")
        for path in image_paths:
            print(f"  - {path}")
        print(f"\n{'─'*60}")
        print("  输入 y 通过，输入 r 打回重新生成，输入 q 退出工作流")
        print(f"{'─'*60}")

        while True:
            choice = input("  请输入: ").strip().lower()
            if choice == "q":
                print("  工作流已退出。")
                sys.exit(0)
            if choice == "y":
                return ReviewDecision(
                    status="approved",
                    feedback="",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            if choice == "r":
                feedback = _collect_structured_feedback()
                return ReviewDecision(
                    status="rejected",
                    feedback=feedback,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            print("  无效输入，请输入 y、r 或 q")

from datetime import datetime, timezone
from models.base import ReviewDecision


class ReviewGate:
    def review_list(self, items: list[dict], step_name: str) -> ReviewDecision:
        """Display items and let user choose one or reject all.

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
        print("  输入数字选择并通过，输入 r 打回重新生成")
        print(f"{'─'*60}")

        while True:
            choice = input("  请输入: ").strip()
            if choice.lower() == "r":
                feedback = input("  请输入修改方向: ").strip()
                return ReviewDecision(
                    status="rejected",
                    feedback=feedback,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            try:
                idx = int(choice)
                if 1 <= idx <= len(items):
                    return ReviewDecision(
                        status="approved",
                        feedback=str(idx),  # store selected index
                        timestamp=datetime.now(timezone.utc).isoformat(),
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
        print("  输入 y 通过，输入 r 打回重新生成")
        print(f"{'─'*60}")

        while True:
            choice = input("  请输入: ").strip().lower()
            if choice == "y":
                return ReviewDecision(
                    status="approved",
                    feedback="",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            if choice == "r":
                feedback = input("  请输入修改方向: ").strip()
                return ReviewDecision(
                    status="rejected",
                    feedback=feedback,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            print("  无效输入，请输入 y 或 r")

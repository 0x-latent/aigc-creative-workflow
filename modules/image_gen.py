import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from google import genai
from google.genai import types

from config import IMAGE_MODEL, MAX_RETRIES, RETRY_BASE_DELAY, logger
from models.base import GenerationMeta
from models.campaign import (
    CampaignGoal,
    GeneratedImage,
    ImageResult,
    Script,
)
from modules.tracker import CampaignTracker

ASPECT_RATIO_16_9 = ", 16:9 aspect ratio, widescreen composition"
ASPECT_RATIO_3_4 = ", 3:4 aspect ratio, vertical portrait composition"

# Platforms that use 3:4 vertical images
VERTICAL_PLATFORMS = {"小红书"}

# Gemini API concurrency limit
GEMINI_MAX_CONCURRENCY = 10


@dataclass
class ImageTask:
    """A single image generation task."""
    scene_no: int
    script_id: str
    prompt: str
    image_path: str
    reference_images: list[str] | None = None
    # Filled after generation
    done: bool = False
    error: str | None = None


class ImageGenerator:
    def __init__(self):
        self.client = genai.Client()
        self.tracker = CampaignTracker()

    def prepare(
        self,
        goal: CampaignGoal,
        script: Script,
        feedback: str = "",
        visual_style: str = "",
        reference_images: list[str] | None = None,
        branch_prefix: str = "",
    ) -> list[ImageTask]:
        """Build image tasks without executing. Returns flat list of tasks."""
        if branch_prefix:
            images_dir = os.path.join("output", goal.campaign_id, "images", branch_prefix)
        else:
            images_dir = os.path.join("output", goal.campaign_id, "images", script.id)
        os.makedirs(images_dir, exist_ok=True)

        style_prefix = visual_style or script.visual_style
        if style_prefix:
            style_prefix = f"Visual style: {style_prefix}. "

        is_vertical = goal.platform in VERTICAL_PLATFORMS
        aspect_hint = ASPECT_RATIO_3_4 if is_vertical else ASPECT_RATIO_16_9
        aspect_check = "3:4" if is_vertical else "16:9"

        tasks = []
        for scene in script.scenes:
            image_path = os.path.join(images_dir, f"scene_{scene.scene_no}.png")
            prompt = scene.image_prompt
            if style_prefix:
                prompt = f"{style_prefix}{prompt}"
            if feedback:
                prompt = f"{prompt}. Additional direction: {feedback}"
            if aspect_check not in prompt:
                prompt += aspect_hint
            tasks.append(ImageTask(
                scene_no=scene.scene_no,
                script_id=script.id,
                prompt=prompt,
                image_path=image_path,
                reference_images=reference_images,
            ))
        return tasks

    def generate_single(self, task: ImageTask) -> None:
        """Generate and save a single image. Blocking call with retry."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                contents = []
                if task.reference_images:
                    from PIL import Image as PILImage
                    for ref_path in task.reference_images[:2]:
                        img = PILImage.open(ref_path)
                        img.thumbnail((1024, 1024))
                        contents.append(img)
                    contents.append(f"参考图中的产品外观必须在生成图中保持一致。{task.prompt}")
                else:
                    contents = [task.prompt]

                response = self.client.models.generate_content(
                    model=IMAGE_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                    ),
                )
                for part in response.candidates[0].content.parts:
                    if part.inline_data is not None:
                        image = part.as_image()
                        image.save(task.image_path)
                        task.done = True
                        return
                raise ValueError("Gemini 响应中未包含图片")
            except Exception as e:
                if attempt == MAX_RETRIES:
                    task.error = str(e)
                    raise
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(f"Gemini 图片生成失败 (尝试 {attempt}/{MAX_RETRIES}): {e}，{delay}s 后重试")
                time.sleep(delay)

    def finalize(
        self,
        goal: CampaignGoal,
        script: Script,
        tasks: list[ImageTask],
        feedback: str = "",
    ) -> ImageResult:
        """Build ImageResult from completed tasks and record to tracker."""
        images = [
            GeneratedImage(
                scene_no=t.scene_no,
                script_id=t.script_id,
                image_prompt=t.prompt,
                image_path=t.image_path,
                model=IMAGE_MODEL,
                generation_params={"prompt": t.prompt},
            )
            for t in tasks
        ]

        input_hash = hashlib.md5(
            "|".join(s.image_prompt for s in script.scenes).encode("utf-8")
        ).hexdigest()

        meta = GenerationMeta(
            prompt_template="",
            model=IMAGE_MODEL,
            timestamp=datetime.now(timezone.utc).isoformat(),
            input_hash=input_hash,
        )

        result = ImageResult(images=images, meta=meta)

        self.tracker.record(
            campaign_id=goal.campaign_id,
            step="image_gen",
            input_snapshot={
                "script_id": script.id,
                "scene_count": len(script.scenes),
                "feedback": feedback,
            },
            output_snapshot={
                "images": [
                    {"scene_no": img.scene_no, "path": img.image_path}
                    for img in images
                ]
            },
            model=IMAGE_MODEL,
            input_hash=input_hash,
        )

        return result

    def generate(
        self,
        goal: CampaignGoal,
        script: Script,
        feedback: str = "",
        visual_style: str = "",
        reference_images: list[str] | None = None,
        branch_prefix: str = "",
    ) -> ImageResult:
        """Synchronous convenience method: prepare + generate all + finalize.

        Used by CLI workflow. API workflow uses prepare/generate_single/finalize
        with its own async scheduler for cross-branch parallelism.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        tasks = self.prepare(goal, script, feedback, visual_style, reference_images, branch_prefix)

        logger.info(f"  并发生成 {len(tasks)} 张场景图片...")
        with ThreadPoolExecutor(max_workers=min(len(tasks), GEMINI_MAX_CONCURRENCY)) as pool:
            futures = {
                pool.submit(self.generate_single, t): t.scene_no
                for t in tasks
            }
            for future in as_completed(futures):
                scene_no = futures[future]
                future.result()
                logger.info(f"  场景 {scene_no} 图片生成完成")

        return self.finalize(goal, script, tasks, feedback)

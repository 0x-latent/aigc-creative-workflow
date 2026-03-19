import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


class ImageGenerator:
    def __init__(self):
        self.client = genai.Client()
        self.tracker = CampaignTracker()

    def generate(
        self,
        goal: CampaignGoal,
        script: Script,
        feedback: str = "",
        visual_style: str = "",
        reference_images: list[str] | None = None,
    ) -> ImageResult:
        images_dir = os.path.join("output", goal.campaign_id, "images")
        os.makedirs(images_dir, exist_ok=True)

        # Determine style prefix
        style_prefix = visual_style or script.visual_style
        if style_prefix:
            style_prefix = f"Visual style: {style_prefix}. "

        # Pick aspect ratio based on platform
        is_vertical = goal.platform in VERTICAL_PLATFORMS
        aspect_hint = ASPECT_RATIO_3_4 if is_vertical else ASPECT_RATIO_16_9
        aspect_check = "3:4" if is_vertical else "16:9"

        # Build tasks
        tasks = []
        for scene in script.scenes:
            image_path = os.path.join(images_dir, f"scene_{scene.scene_no}.png")
            prompt = scene.image_prompt
            if style_prefix:
                prompt = f"{style_prefix}{prompt}"
            if feedback:
                prompt = f"{prompt}. Additional direction: {feedback}"
            # Ensure aspect ratio hint is present
            if aspect_check not in prompt:
                prompt += aspect_hint
            tasks.append((scene, prompt, image_path))

        # Generate images concurrently
        logger.info(f"  并发生成 {len(tasks)} 张场景图片...")
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(self._generate_and_save, prompt, path, reference_images): scene.scene_no
                for scene, prompt, path in tasks
            }
            for future in as_completed(futures):
                scene_no = futures[future]
                future.result()  # raise if failed
                logger.info(f"  场景 {scene_no} 图片生成完成")

        images = [
            GeneratedImage(
                scene_no=scene.scene_no,
                script_id=script.id,
                image_prompt=prompt,
                image_path=image_path,
                model=IMAGE_MODEL,
                generation_params={"prompt": prompt},
            )
            for scene, prompt, image_path in tasks
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

    def _generate_and_save(self, prompt: str, image_path: str, reference_images: list[str] | None = None):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Build contents with optional reference images
                contents = []
                if reference_images:
                    from PIL import Image as PILImage
                    for ref_path in reference_images[:2]:  # max 2 to avoid token limit
                        img = PILImage.open(ref_path)
                        img.thumbnail((1024, 1024))
                        contents.append(img)
                    contents.append(f"参考图中的产品外观必须在生成图中保持一致。{prompt}")
                else:
                    contents = [prompt]

                response = self.client.models.generate_content(
                    model=IMAGE_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                    ),
                )
                # Extract image from response parts
                for part in response.candidates[0].content.parts:
                    if part.inline_data is not None:
                        image = part.as_image()
                        image.save(image_path)
                        return
                raise ValueError("Gemini 响应中未包含图片")
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(f"Gemini 图片生成失败 (尝试 {attempt}/{MAX_RETRIES}): {e}，{delay}s 后重试")
                time.sleep(delay)
        raise RuntimeError(f"图片生成在 {MAX_RETRIES} 次重试后仍然失败")

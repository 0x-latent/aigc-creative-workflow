import hashlib
import os
import requests
from datetime import datetime, timezone

import replicate

from models.base import GenerationMeta
from models.campaign import (
    CampaignGoal,
    GeneratedImage,
    ImageResult,
    Script,
)
from modules.tracker import CampaignTracker

REPLICATE_MODEL = "black-forest-labs/flux-dev"


class ImageGenerator:
    def __init__(self):
        self.tracker = CampaignTracker()

    def generate(
        self, goal: CampaignGoal, script: Script
    ) -> ImageResult:
        images_dir = os.path.join("output", goal.campaign_id, "images")
        os.makedirs(images_dir, exist_ok=True)

        images = []
        for scene in script.scenes:
            image_path = os.path.join(images_dir, f"scene_{scene.scene_no}.png")

            params = {
                "prompt": scene.image_prompt,
                "num_outputs": 1,
                "aspect_ratio": "16:9",
                "output_format": "png",
            }

            print(f"  正在生成场景 {scene.scene_no} 图片...")
            output = replicate.run(REPLICATE_MODEL, input=params)

            # flux-dev returns a list of FileOutput objects
            image_url = str(output[0]) if isinstance(output, list) else str(output)
            resp = requests.get(image_url)
            resp.raise_for_status()
            with open(image_path, "wb") as f:
                f.write(resp.content)

            images.append(
                GeneratedImage(
                    scene_no=scene.scene_no,
                    script_id=script.id,
                    image_prompt=scene.image_prompt,
                    image_path=image_path,
                    model=REPLICATE_MODEL,
                    generation_params=params,
                )
            )

        input_hash = hashlib.md5(
            "|".join(s.image_prompt for s in script.scenes).encode("utf-8")
        ).hexdigest()

        meta = GenerationMeta(
            prompt_template="",
            model=REPLICATE_MODEL,
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
            },
            output_snapshot={
                "images": [
                    {"scene_no": img.scene_no, "path": img.image_path}
                    for img in images
                ]
            },
            model=REPLICATE_MODEL,
            input_hash=input_hash,
        )

        return result

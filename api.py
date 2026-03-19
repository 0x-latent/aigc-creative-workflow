"""FastAPI backend for AIGC Creative Workflow — multi-select branching."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import logger
from db import init_db
from models.campaign import CampaignGoal
from modules.brand_kb import BrandKBReader
from modules.concept_gen import ConceptGenerator
from modules.direction_gen import DirectionGenerator
from modules.image_gen import ImageGenerator
from modules.insights import InsightsLoader
from modules.platform_kb import PlatformKBReader
from modules.script_gen import ScriptGenerator
from modules.tracker import CampaignTracker

# Concurrency limiter for LLM calls
llm_semaphore = asyncio.Semaphore(3)


@asynccontextmanager
async def lifespan(app):
    init_db()
    os.makedirs("web", exist_ok=True)
    os.makedirs("output", exist_ok=True)
    yield


app = FastAPI(title="AIGC Creative Workflow", lifespan=lifespan)

# In-memory campaign state
campaigns: dict = {}


# ── Request Models ──


class CreateReq(BaseModel):
    brand_id: str
    objective: str
    platform: str
    notes: str = ""


class FeedbackReq(BaseModel):
    feedback: str = ""


class SelectReq(BaseModel):
    index: int


class MultiSelectReq(BaseModel):
    indices: list[int]


class StyleReq(BaseModel):
    style: str


# ── Helpers ──


def _get(cid: str) -> dict:
    if cid not in campaigns:
        raise HTTPException(404, "Campaign not found")
    return campaigns[cid]


def _get_concept_branch(s: dict, ci: int):
    """Get or validate a concept branch by index."""
    branches = s.get("branches") or []
    for b in branches:
        if b["concept_index"] == ci:
            return b
    raise HTTPException(404, f"Concept branch {ci} not found")


def _get_direction_branch(concept_branch: dict, di: int):
    """Get or validate a direction branch by index."""
    branches = concept_branch.get("direction_branches") or []
    for b in branches:
        if b["direction_index"] == di:
            return b
    raise HTTPException(404, f"Direction branch {di} not found")


def _get_script_branch(direction_branch: dict, si: int):
    """Get or validate a script branch by index."""
    branches = direction_branch.get("script_branches") or []
    for b in branches:
        if b["script_index"] == si:
            return b
    raise HTTPException(404, f"Script branch {si} not found")


def _serialize_script(sc):
    return {
        "id": sc.id,
        "outline": sc.outline,
        "visual_style": sc.visual_style,
        "scenes": [
            {
                "scene_no": sn.scene_no,
                "duration_sec": sn.duration_sec,
                "visual_description": sn.visual_description,
                "voiceover": sn.voiceover,
                "image_prompt": sn.image_prompt,
                "page_type": sn.page_type,
            }
            for sn in sc.scenes
        ],
    }


def _serialize_image(img):
    return {
        "scene_no": img.scene_no,
        "image_prompt": img.image_prompt,
        "image_path": img.image_path.replace("\\", "/"),
    }


# ── Brands ──


@app.get("/api/brands")
async def list_brands():
    brands_dir = "brands"
    result = []
    if os.path.isdir(brands_dir):
        for name in sorted(os.listdir(brands_dir)):
            kb_path = os.path.join(brands_dir, name, "knowledge_base.md")
            if os.path.isfile(kb_path):
                brand_name = name
                with open(kb_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("# "):
                            brand_name = line[2:].strip()
                            break
                result.append({"id": name, "name": brand_name})
    return {"brands": result}


# ── Campaign ──


@app.post("/api/campaigns")
async def create_campaign(req: CreateReq):
    campaign_id = f"campaign_{uuid.uuid4().hex[:8]}"

    try:
        brand_kb = BrandKBReader().load(req.brand_id)
        insights = InsightsLoader().load(req.brand_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    platform_kb = PlatformKBReader().load(req.platform)
    brand_images = BrandKBReader().discover_brand_images(req.brand_id)

    goal = CampaignGoal(
        campaign_id=campaign_id,
        brand_id=req.brand_id,
        objective=req.objective,
        platform=req.platform,
        notes=req.notes,
    )

    campaigns[campaign_id] = {
        "goal": goal,
        "brand_kb": brand_kb,
        "insights": insights,
        "platform_kb": platform_kb.raw_md,
        "brand_images": brand_images,
        # Tree state
        "concepts": None,
        "selected_concept_indices": None,
        "branches": None,  # list of concept branch dicts
    }

    CampaignTracker().record(
        campaign_id=campaign_id,
        step="campaign_created",
        input_snapshot={"brand_id": req.brand_id, "objective": req.objective},
        output_snapshot={"brand_name": brand_kb.name},
    )

    return {
        "campaign_id": campaign_id,
        "brand_name": brand_kb.name,
        "brand_version": brand_kb.version[:8],
        "insights_sources": [os.path.basename(s) for s in insights.sources],
        "platform_kb_loaded": bool(platform_kb.raw_md),
        "brand_images": [p.replace("\\", "/") for p in brand_images],
    }


# ── Concepts ──


@app.post("/api/campaigns/{cid}/concepts")
async def generate_concepts(cid: str, req: FeedbackReq = None):
    req = req or FeedbackReq()
    s = _get(cid)
    gen = ConceptGenerator()
    async with llm_semaphore:
        result = await asyncio.to_thread(
            gen.generate, s["goal"], s["brand_kb"], s["insights"], req.feedback
        )
    s["concepts"] = result.concepts
    s["selected_concept_indices"] = None
    s["branches"] = None
    return {
        "concepts": [
            {"id": c.id, "title": c.title, "description": c.description, "rationale": c.rationale}
            for c in result.concepts
        ]
    }


@app.post("/api/campaigns/{cid}/concepts/select")
async def select_concepts(cid: str, req: MultiSelectReq):
    s = _get(cid)
    if not s["concepts"]:
        raise HTTPException(400, "Generate concepts first")
    for idx in req.indices:
        if not (0 <= idx < len(s["concepts"])):
            raise HTTPException(400, f"Invalid index: {idx}")
    s["selected_concept_indices"] = req.indices
    # Create concept branches
    s["branches"] = [
        {
            "concept_index": ci,
            "directions": None,
            "selected_direction_indices": None,
            "direction_branches": None,
        }
        for ci in req.indices
    ]
    return {
        "selected": [
            {"index": ci, "title": s["concepts"][ci].title}
            for ci in req.indices
        ]
    }


# ── Directions (per concept branch) ──


@app.post("/api/campaigns/{cid}/branches/{ci}/directions")
async def generate_directions(cid: str, ci: int, req: FeedbackReq = None):
    req = req or FeedbackReq()
    s = _get(cid)
    branch = _get_concept_branch(s, ci)
    concept = s["concepts"][ci]
    gen = DirectionGenerator()
    async with llm_semaphore:
        result = await asyncio.to_thread(
            gen.generate, s["goal"], s["brand_kb"], concept, req.feedback,
            platform_kb=s["platform_kb"],
        )
    branch["directions"] = result.directions
    branch["selected_direction_indices"] = None
    branch["direction_branches"] = None
    return {
        "concept_index": ci,
        "directions": [
            {"id": d.id, "title": d.title, "description": d.description, "platform_notes": d.platform_notes}
            for d in result.directions
        ]
    }


@app.post("/api/campaigns/{cid}/branches/{ci}/directions/select")
async def select_directions(cid: str, ci: int, req: MultiSelectReq):
    s = _get(cid)
    branch = _get_concept_branch(s, ci)
    if not branch["directions"]:
        raise HTTPException(400, "Generate directions first")
    for idx in req.indices:
        if not (0 <= idx < len(branch["directions"])):
            raise HTTPException(400, f"Invalid index: {idx}")
    branch["selected_direction_indices"] = req.indices
    branch["direction_branches"] = [
        {
            "direction_index": di,
            "scripts": None,
            "selected_script_indices": None,
            "script_branches": None,
        }
        for di in req.indices
    ]
    return {
        "selected": [
            {"index": di, "title": branch["directions"][di].title}
            for di in req.indices
        ]
    }


# ── Scripts (per direction branch) ──


@app.post("/api/campaigns/{cid}/branches/{ci}/{di}/scripts")
async def generate_scripts(cid: str, ci: int, di: int, req: FeedbackReq = None):
    req = req or FeedbackReq()
    s = _get(cid)
    concept_branch = _get_concept_branch(s, ci)
    dir_branch = _get_direction_branch(concept_branch, di)
    direction = concept_branch["directions"][di]
    gen = ScriptGenerator()
    async with llm_semaphore:
        result = await asyncio.to_thread(
            gen.generate, s["goal"], s["brand_kb"], direction, feedback=req.feedback,
            platform_kb=s["platform_kb"],
        )
    dir_branch["scripts"] = result.scripts
    dir_branch["selected_script_indices"] = None
    dir_branch["script_branches"] = None
    return {
        "concept_index": ci,
        "direction_index": di,
        "scripts": [_serialize_script(sc) for sc in result.scripts],
    }


@app.post("/api/campaigns/{cid}/branches/{ci}/{di}/scripts/select")
async def select_scripts(cid: str, ci: int, di: int, req: MultiSelectReq):
    s = _get(cid)
    concept_branch = _get_concept_branch(s, ci)
    dir_branch = _get_direction_branch(concept_branch, di)
    if not dir_branch["scripts"]:
        raise HTTPException(400, "Generate scripts first")
    for idx in req.indices:
        if not (0 <= idx < len(dir_branch["scripts"])):
            raise HTTPException(400, f"Invalid index: {idx}")
    dir_branch["selected_script_indices"] = req.indices
    dir_branch["script_branches"] = [
        {
            "script_index": si,
            "confirmed_style": "",
            "images": None,
        }
        for si in req.indices
    ]
    return {
        "selected": [
            {"index": si, "outline": dir_branch["scripts"][si].outline}
            for si in req.indices
        ]
    }


# ── Style (per script branch) ──


@app.post("/api/campaigns/{cid}/branches/{ci}/{di}/{si}/style")
async def confirm_style(cid: str, ci: int, di: int, si: int, req: StyleReq):
    s = _get(cid)
    concept_branch = _get_concept_branch(s, ci)
    dir_branch = _get_direction_branch(concept_branch, di)
    script_branch = _get_script_branch(dir_branch, si)
    script_branch["confirmed_style"] = req.style
    return {"style": req.style}


# ── Images (per script branch) ──


@app.post("/api/campaigns/{cid}/branches/{ci}/{di}/{si}/images")
async def generate_images(cid: str, ci: int, di: int, si: int, req: FeedbackReq = None):
    req = req or FeedbackReq()
    s = _get(cid)
    concept_branch = _get_concept_branch(s, ci)
    dir_branch = _get_direction_branch(concept_branch, di)
    script_branch = _get_script_branch(dir_branch, si)
    script = dir_branch["scripts"][si]
    visual_style = script_branch.get("confirmed_style", "")
    gen = ImageGenerator()
    async with llm_semaphore:
        result = await asyncio.to_thread(
            gen.generate, s["goal"], script, feedback=req.feedback,
            visual_style=visual_style, reference_images=s.get("brand_images"),
        )
    script_branch["images"] = result.images
    return {
        "concept_index": ci,
        "direction_index": di,
        "script_index": si,
        "images": [_serialize_image(img) for img in result.images],
    }


# ── Task Estimate ──


@app.get("/api/campaigns/{cid}/estimate")
async def estimate_tasks(cid: str):
    s = _get(cid)
    # Count pending generation tasks based on current tree state
    task_count = 0
    branches = s.get("branches") or []
    for cb in branches:
        if cb.get("directions") is None:
            task_count += 1  # direction gen needed
        dir_branches = cb.get("direction_branches") or []
        for db in dir_branches:
            if db.get("scripts") is None:
                task_count += 1  # script gen needed
            script_branches = db.get("script_branches") or []
            for sb in script_branches:
                if sb.get("images") is None:
                    task_count += 1  # image gen needed
    # Rough estimate: ~30s per LLM call
    est_minutes = max(1, (task_count * 30) // 60)
    return {
        "task_count": task_count,
        "estimated_minutes": est_minutes,
    }


# ── Batch generation helpers ──


@app.post("/api/campaigns/{cid}/branches/{ci}/directions/generate_all")
async def generate_all_scripts_for_concept(cid: str, ci: int):
    """Generate scripts for all selected directions in a concept branch concurrently."""
    s = _get(cid)
    concept_branch = _get_concept_branch(s, ci)
    dir_branches = concept_branch.get("direction_branches") or []
    if not dir_branches:
        raise HTTPException(400, "Select directions first")

    async def gen_scripts(db):
        di = db["direction_index"]
        direction = concept_branch["directions"][di]
        gen = ScriptGenerator()
        async with llm_semaphore:
            result = await asyncio.to_thread(
                gen.generate, s["goal"], s["brand_kb"], direction,
                platform_kb=s["platform_kb"],
            )
        db["scripts"] = result.scripts
        db["selected_script_indices"] = None
        db["script_branches"] = None
        return {
            "direction_index": di,
            "scripts": [_serialize_script(sc) for sc in result.scripts],
        }

    results = await asyncio.gather(*[gen_scripts(db) for db in dir_branches])
    return {"results": results}


# ── Summary — all creative plans ──


@app.get("/api/campaigns/{cid}/summary")
async def campaign_summary(cid: str):
    s = _get(cid)
    plans = []
    branches = s.get("branches") or []
    for cb in branches:
        ci = cb["concept_index"]
        concept = s["concepts"][ci]
        for db in (cb.get("direction_branches") or []):
            di = db["direction_index"]
            direction = cb["directions"][di]
            for sb in (db.get("script_branches") or []):
                si = sb["script_index"]
                script = db["scripts"][si]
                images = sb.get("images") or []
                plans.append({
                    "concept": {"index": ci, "title": concept.title, "description": concept.description, "rationale": concept.rationale},
                    "direction": {"index": di, "title": direction.title, "description": direction.description, "platform_notes": direction.platform_notes},
                    "script": _serialize_script(script),
                    "visual_style": sb.get("confirmed_style", script.visual_style),
                    "images": [_serialize_image(img) for img in images],
                })
    return {"plans": plans, "total": len(plans)}


# ── Static files ──

app.mount("/output", StaticFiles(directory="output"), name="output")


@app.get("/")
async def index():
    return FileResponse("web/index.html")


@app.get("/{path:path}")
async def static_files(path: str):
    file_path = os.path.join("web", path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    raise HTTPException(404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)

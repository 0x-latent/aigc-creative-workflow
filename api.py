"""FastAPI backend for AIGC Creative Workflow — multi-select branching."""

import asyncio
import json as jsonlib
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import logger
from db import init_db
from models.brand import BrandKB, InsightsBundle
from models.campaign import (
    CampaignGoal,
    Concept,
    Direction,
    GeneratedImage,
    Scene,
    Script,
)
from modules.brand_kb import BrandKBReader
from modules.concept_gen import ConceptGenerator
from modules.direction_gen import DirectionGenerator
from modules.image_gen import ImageGenerator
from modules.insights import InsightsLoader
from modules.platform_kb import PlatformKBReader
from modules.script_gen import ScriptGenerator
from modules.tracker import CampaignTracker

# Concurrency limiters
llm_semaphore = asyncio.Semaphore(3)   # text LLM (Claude)
image_semaphore = asyncio.Semaphore(10)  # individual Gemini image API calls


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


class MergeReq(BaseModel):
    level: str  # "concept" | "direction" | "script"
    concept_index: int | None = None
    direction_index: int | None = None
    indices: list[int]
    instruction: str = ""


# ── Persistence helpers ──


def _serialize_campaign(s: dict) -> dict:
    """Convert in-memory campaign state to JSON-safe dict."""
    def _ser_concepts(concepts):
        if not concepts:
            return None
        return [asdict(c) for c in concepts]

    def _ser_directions(directions):
        if not directions:
            return None
        return [asdict(d) for d in directions]

    def _ser_scripts(scripts):
        if not scripts:
            return None
        return [_serialize_script(sc) for sc in scripts]

    def _ser_images(images):
        if not images:
            return None
        return [_serialize_image(img) for img in images]

    def _ser_branches(branches):
        if not branches:
            return None
        result = []
        for cb in branches:
            cb_out = {
                "concept_index": cb["concept_index"],
                "directions": _ser_directions(cb.get("directions")),
                "selected_direction_indices": cb.get("selected_direction_indices"),
                "skipped": cb.get("skipped", False),
                "direction_branches": None,
            }
            if cb.get("direction_branches"):
                cb_out["direction_branches"] = []
                for db in cb["direction_branches"]:
                    db_out = {
                        "direction_index": db["direction_index"],
                        "scripts": _ser_scripts(db.get("scripts")),
                        "selected_script_indices": db.get("selected_script_indices"),
                        "skipped": db.get("skipped", False),
                        "script_branches": None,
                    }
                    if db.get("script_branches"):
                        db_out["script_branches"] = [
                            {
                                "script_index": sb["script_index"],
                                "confirmed_style": sb.get("confirmed_style", ""),
                                "images": _ser_images(sb.get("images")),
                            }
                            for sb in db["script_branches"]
                        ]
                    cb_out["direction_branches"].append(db_out)
            result.append(cb_out)
        return result

    return {
        "goal": asdict(s["goal"]),
        "brand_kb": asdict(s["brand_kb"]),
        "insights": asdict(s["insights"]),
        "platform_kb": s["platform_kb"],
        "brand_images": s.get("brand_images", []),
        "concepts": _ser_concepts(s.get("concepts")),
        "selected_concept_indices": s.get("selected_concept_indices"),
        "branches": _ser_branches(s.get("branches")),
    }


def _deserialize_campaign(data: dict) -> dict:
    """Rebuild in-memory campaign state from JSON."""
    def _deser_concepts(items):
        if not items:
            return None
        return [Concept(**c) for c in items]

    def _deser_directions(items):
        if not items:
            return None
        return [Direction(**d) for d in items]

    def _deser_scripts(items):
        if not items:
            return None
        scripts = []
        for sd in items:
            scenes = [Scene(**sn) for sn in sd.get("scenes", [])]
            scripts.append(Script(
                id=sd["id"], outline=sd["outline"],
                scenes=scenes, visual_style=sd.get("visual_style", ""),
            ))
        return scripts

    def _deser_images(items):
        if not items:
            return None
        return [GeneratedImage(
            scene_no=img["scene_no"],
            script_id=img.get("script_id", ""),
            image_prompt=img.get("image_prompt", ""),
            image_path=img.get("image_path", ""),
            model=img.get("model", ""),
            generation_params=img.get("generation_params", {}),
        ) for img in items]

    def _deser_branches(branches_data):
        if not branches_data:
            return None
        result = []
        for cb in branches_data:
            cb_out = {
                "concept_index": cb["concept_index"],
                "directions": _deser_directions(cb.get("directions")),
                "selected_direction_indices": cb.get("selected_direction_indices"),
                "skipped": cb.get("skipped", False),
                "direction_branches": None,
            }
            if cb.get("direction_branches"):
                cb_out["direction_branches"] = []
                for db in cb["direction_branches"]:
                    db_out = {
                        "direction_index": db["direction_index"],
                        "scripts": _deser_scripts(db.get("scripts")),
                        "selected_script_indices": db.get("selected_script_indices"),
                        "skipped": db.get("skipped", False),
                        "script_branches": None,
                    }
                    if db.get("script_branches"):
                        db_out["script_branches"] = [
                            {
                                "script_index": sb["script_index"],
                                "confirmed_style": sb.get("confirmed_style", ""),
                                "images": _deser_images(sb.get("images")),
                            }
                            for sb in db["script_branches"]
                        ]
                    cb_out["direction_branches"].append(db_out)
            result.append(cb_out)
        return result

    goal_data = data["goal"]
    return {
        "goal": CampaignGoal(**goal_data),
        "brand_kb": BrandKB(**data["brand_kb"]),
        "insights": InsightsBundle(**data["insights"]),
        "platform_kb": data.get("platform_kb", ""),
        "brand_images": data.get("brand_images", []),
        "concepts": _deser_concepts(data.get("concepts")),
        "selected_concept_indices": data.get("selected_concept_indices"),
        "branches": _deser_branches(data.get("branches")),
    }


def _save_campaign(cid: str):
    """Atomically persist campaign state to disk."""
    if cid not in campaigns:
        return
    s = campaigns[cid]
    out_dir = os.path.join("output", cid)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "campaign_state.json")
    tmp = path + ".tmp"
    payload = _serialize_campaign(s)
    with open(tmp, "w", encoding="utf-8") as f:
        jsonlib.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _campaign_step_label(s: dict) -> str:
    """Return a human-readable progress label."""
    if s.get("branches"):
        for cb in s["branches"]:
            for db in (cb.get("direction_branches") or []):
                for sb in (db.get("script_branches") or []):
                    if sb.get("images"):
                        return "已完成"
                if db.get("scripts"):
                    return "脚本已生成"
            if cb.get("directions"):
                return "方向已生成"
        return "概念已选择"
    if s.get("selected_concept_indices"):
        return "概念已选择"
    if s.get("concepts"):
        return "概念已生成"
    return "已创建"


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

    _save_campaign(campaign_id)

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
    _save_campaign(cid)
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
    if not req.indices:
        raise HTTPException(400, "Must select at least one concept")
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
    _save_campaign(cid)
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
    _save_campaign(cid)
    return {
        "concept_index": ci,
        "directions": [
            {"id": d.id, "title": d.title, "description": d.description, "platform_notes": d.platform_notes}
            for d in result.directions
        ]
    }


@app.post("/api/campaigns/{cid}/branches/{ci}/directions/select")
async def select_directions(cid: str, ci: int, req: MultiSelectReq):
    """Select directions. Pass indices=[] to skip this concept branch entirely."""
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
    branch["skipped"] = len(req.indices) == 0
    _save_campaign(cid)
    return {
        "selected": [
            {"index": di, "title": branch["directions"][di].title}
            for di in req.indices
        ],
        "skipped": branch["skipped"],
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
    _save_campaign(cid)
    return {
        "concept_index": ci,
        "direction_index": di,
        "scripts": [_serialize_script(sc) for sc in result.scripts],
    }


@app.post("/api/campaigns/{cid}/branches/{ci}/{di}/scripts/select")
async def select_scripts(cid: str, ci: int, di: int, req: MultiSelectReq):
    """Select scripts. Pass indices=[] to skip this direction branch entirely."""
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
    dir_branch["skipped"] = len(req.indices) == 0
    _save_campaign(cid)
    return {
        "selected": [
            {"index": si, "outline": dir_branch["scripts"][si].outline}
            for si in req.indices
        ],
        "skipped": dir_branch["skipped"],
    }


# ── Style (per script branch) ──


@app.post("/api/campaigns/{cid}/branches/{ci}/{di}/{si}/style")
async def confirm_style(cid: str, ci: int, di: int, si: int, req: StyleReq):
    s = _get(cid)
    concept_branch = _get_concept_branch(s, ci)
    dir_branch = _get_direction_branch(concept_branch, di)
    script_branch = _get_script_branch(dir_branch, si)
    script_branch["confirmed_style"] = req.style
    _save_campaign(cid)
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
    branch_prefix = f"c{ci}_d{di}_s{si}"
    tasks = gen.prepare(
        s["goal"], script, feedback=req.feedback,
        visual_style=visual_style, reference_images=s.get("brand_images"),
        branch_prefix=branch_prefix,
    )
    # Generate all images for this branch with concurrency control
    async def gen_one(t):
        async with image_semaphore:
            await asyncio.to_thread(gen.generate_single, t)

    await asyncio.gather(*[gen_one(t) for t in tasks])
    result = gen.finalize(s["goal"], script, tasks, req.feedback)
    script_branch["images"] = result.images
    _save_campaign(cid)
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


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {jsonlib.dumps(data, ensure_ascii=False)}\n\n"


# ── Batch generation helpers ──


@app.post("/api/campaigns/{cid}/directions/generate_all")
async def generate_all_directions(cid: str):
    """Generate directions for ALL selected concept branches concurrently. Returns SSE stream."""
    s = _get(cid)
    branches = s.get("branches") or []
    if not branches:
        raise HTTPException(400, "Select concepts first")

    # Build sibling info
    sibling_map = {}
    for cb in branches:
        ci = cb["concept_index"]
        others = [
            f"- 理念「{s['concepts'][ob['concept_index']].title}」: {s['concepts'][ob['concept_index']].description}"
            for ob in branches if ob["concept_index"] != ci
        ]
        sibling_map[ci] = "\n".join(others) if others else ""

    async def gen_directions(cb):
        ci = cb["concept_index"]
        concept = s["concepts"][ci]
        gen = DirectionGenerator()
        async with llm_semaphore:
            result = await asyncio.to_thread(
                gen.generate, s["goal"], s["brand_kb"], concept, "",
                platform_kb=s["platform_kb"],
                sibling_info=sibling_map[ci],
            )
        cb["directions"] = result.directions
        cb["selected_direction_indices"] = None
        cb["direction_branches"] = None
        _save_campaign(cid)
        return {
            "concept_index": ci,
            "directions": [
                {"id": d.id, "title": d.title, "description": d.description, "platform_notes": d.platform_notes}
                for d in result.directions
            ],
        }

    async def stream():
        tasks = [asyncio.create_task(gen_directions(cb)) for cb in branches]
        yield _sse_event({"type": "start", "total": len(tasks)})
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                yield _sse_event({"type": "item", **result})
            except Exception as e:
                yield _sse_event({"type": "error", "message": str(e)})
        yield _sse_event({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/campaigns/{cid}/scripts/generate_all")
async def generate_all_scripts(cid: str):
    """Generate scripts for ALL direction branches concurrently. Returns SSE stream."""
    s = _get(cid)
    branches = s.get("branches") or []
    if not branches:
        raise HTTPException(400, "No concept branches")

    # Collect all pending tasks and build sibling info
    pending = []
    all_directions = []
    for cb in branches:
        ci = cb["concept_index"]
        for db in (cb.get("direction_branches") or []):
            di = db["direction_index"]
            direction = cb["directions"][di]
            all_directions.append((ci, di, direction))
            if db.get("scripts") is not None:
                continue
            pending.append((ci, di, direction, db))

    if not pending:
        raise HTTPException(400, "No pending script generation tasks")

    sibling_map = {}
    for ci, di, direction in all_directions:
        others = [
            f"- 方向「{od.title}」(理念{oci}): {od.description}"
            for oci, odi, od in all_directions if (oci, odi) != (ci, di)
        ]
        sibling_map[(ci, di)] = "\n".join(others) if others else ""

    async def gen_scripts(ci, di, direction, db):
        gen = ScriptGenerator()
        async with llm_semaphore:
            result = await asyncio.to_thread(
                gen.generate, s["goal"], s["brand_kb"], direction,
                platform_kb=s["platform_kb"],
                sibling_info=sibling_map[(ci, di)],
            )
        db["scripts"] = result.scripts
        db["selected_script_indices"] = None
        db["script_branches"] = None
        _save_campaign(cid)
        return {
            "concept_index": ci,
            "direction_index": di,
            "scripts": [_serialize_script(sc) for sc in result.scripts],
        }

    async def stream():
        tasks = [asyncio.create_task(gen_scripts(ci, di, d, db)) for ci, di, d, db in pending]
        yield _sse_event({"type": "start", "total": len(tasks)})
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                yield _sse_event({"type": "item", **result})
            except Exception as e:
                yield _sse_event({"type": "error", "message": str(e)})
        yield _sse_event({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/campaigns/{cid}/images/generate_all")
async def generate_all_images(cid: str):
    """Generate images for ALL script branches concurrently. Returns SSE stream.

    Flattens all individual image tasks into a single pool (max 40 concurrent),
    then streams branch-level results as each branch's images are all done.
    """
    s = _get(cid)
    branches = s.get("branches") or []
    if not branches:
        raise HTTPException(400, "No concept branches")

    gen = ImageGenerator()
    branch_tasks = []
    total_images = 0

    for cb in branches:
        ci = cb["concept_index"]
        for db in (cb.get("direction_branches") or []):
            di = db["direction_index"]
            for sb in (db.get("script_branches") or []):
                si = sb["script_index"]
                if sb.get("images") is not None:
                    continue
                script = db["scripts"][si]
                visual_style = sb.get("confirmed_style", "")
                tasks = gen.prepare(
                    s["goal"], script,
                    visual_style=visual_style,
                    reference_images=s.get("brand_images"),
                    branch_prefix=f"c{ci}_d{di}_s{si}",
                )
                branch_tasks.append((ci, di, si, script, sb, tasks))
                total_images += len(tasks)

    if not branch_tasks:
        raise HTTPException(400, "No pending image generation tasks")

    logger.info(f"  调度 {total_images} 张图片生成（{len(branch_tasks)} 个分支），最大并发 {image_semaphore._value}")

    async def gen_one(t):
        async with image_semaphore:
            await asyncio.to_thread(gen.generate_single, t)

    async def gen_branch(ci, di, si, script, sb, tasks):
        """Generate all images for one branch, then finalize."""
        await asyncio.gather(*[gen_one(t) for t in tasks])
        result = gen.finalize(s["goal"], script, tasks)
        sb["images"] = result.images
        _save_campaign(cid)
        return {
            "concept_index": ci,
            "direction_index": di,
            "script_index": si,
            "images": [_serialize_image(img) for img in result.images],
        }

    async def stream():
        coros = [
            asyncio.create_task(gen_branch(ci, di, si, sc, sb, tasks))
            for ci, di, si, sc, sb, tasks in branch_tasks
        ]
        yield _sse_event({"type": "start", "total_branches": len(coros), "total_images": total_images})
        for coro in asyncio.as_completed(coros):
            try:
                result = await coro
                yield _sse_event({"type": "item", **result})
            except Exception as e:
                yield _sse_event({"type": "error", "message": str(e)})
        yield _sse_event({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Campaign list & load ──


@app.get("/api/campaigns")
async def list_campaigns():
    """List all persisted campaigns from output/ directory."""
    result = []
    out_dir = "output"
    if not os.path.isdir(out_dir):
        return {"campaigns": []}
    for name in sorted(os.listdir(out_dir), reverse=True):
        state_path = os.path.join(out_dir, name, "campaign_state.json")
        if not os.path.isfile(state_path):
            continue
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = jsonlib.load(f)
            goal = data.get("goal", {})
            brand_kb = data.get("brand_kb", {})
            # Compute step label from serialized data
            step_label = "已创建"
            if data.get("branches"):
                step_label = "概念已选择"
                for cb in data["branches"]:
                    if cb.get("directions"):
                        step_label = "方向已生成"
                    for db in (cb.get("direction_branches") or []):
                        if db.get("scripts"):
                            step_label = "脚本已生成"
                        for sb in (db.get("script_branches") or []):
                            if sb.get("images"):
                                step_label = "已完成"
            elif data.get("concepts"):
                step_label = "概念已生成"
            stat = os.stat(state_path)
            result.append({
                "campaign_id": name,
                "brand_id": goal.get("brand_id", ""),
                "brand_name": brand_kb.get("name", goal.get("brand_id", "")),
                "objective": goal.get("objective", ""),
                "platform": goal.get("platform", ""),
                "step_label": step_label,
                "updated_at": stat.st_mtime,
            })
        except (jsonlib.JSONDecodeError, KeyError):
            continue
    return {"campaigns": result}


@app.get("/api/campaigns/{cid}/load")
async def load_campaign(cid: str):
    """Load a persisted campaign into memory and return full state for frontend."""
    state_path = os.path.join("output", cid, "campaign_state.json")
    if not os.path.isfile(state_path):
        raise HTTPException(404, f"Campaign state not found: {cid}")
    with open(state_path, "r", encoding="utf-8") as f:
        data = jsonlib.load(f)
    s = _deserialize_campaign(data)
    campaigns[cid] = s

    # Build response with full tree state for frontend reconstruction
    goal = s["goal"]
    brand_kb = s["brand_kb"]
    insights = s["insights"]

    resp: dict = {
        "campaign_id": cid,
        "brand_name": brand_kb.name,
        "brand_version": brand_kb.version[:8],
        "insights_sources": [os.path.basename(src) for src in insights.sources],
        "platform_kb_loaded": bool(s["platform_kb"]),
        "brand_images": [p.replace("\\", "/") for p in s.get("brand_images", [])],
        "objective": goal.objective,
        "platform": goal.platform,
        "notes": goal.notes,
    }
    # Concepts
    if s.get("concepts"):
        resp["concepts"] = [
            {"id": c.id, "title": c.title, "description": c.description, "rationale": c.rationale}
            for c in s["concepts"]
        ]
    resp["selected_concept_indices"] = s.get("selected_concept_indices")

    # Branches → frontend-compatible format
    if s.get("branches"):
        branches_out = {}
        for cb in s["branches"]:
            ci = cb["concept_index"]
            cb_out: dict = {
                "directions": None,
                "selectedDirectionIndices": cb.get("selected_direction_indices"),
                "directionBranches": {},
            }
            if cb.get("directions"):
                cb_out["directions"] = [
                    {"id": d.id, "title": d.title, "description": d.description, "platform_notes": d.platform_notes}
                    for d in cb["directions"]
                ]
            if cb.get("direction_branches"):
                for db in cb["direction_branches"]:
                    di = db["direction_index"]
                    db_out: dict = {
                        "scripts": None,
                        "selectedScriptIndices": db.get("selected_script_indices"),
                        "scriptBranches": {},
                    }
                    if db.get("scripts"):
                        db_out["scripts"] = [_serialize_script(sc) for sc in db["scripts"]]
                    if db.get("script_branches"):
                        for sb in db["script_branches"]:
                            si = sb["script_index"]
                            sb_out = {
                                "confirmed_style": sb.get("confirmed_style", ""),
                                "images": [_serialize_image(img) for img in sb["images"]] if sb.get("images") else None,
                            }
                            db_out["scriptBranches"][str(si)] = sb_out
                    cb_out["directionBranches"][str(di)] = db_out
            branches_out[str(ci)] = cb_out
        resp["branches"] = branches_out

    return resp


# ── Merge ──


@app.post("/api/campaigns/{cid}/merge")
async def merge_items(cid: str, req: MergeReq):
    """Merge multiple items into a new generation via constructed feedback."""
    s = _get(cid)
    if len(req.indices) < 2:
        raise HTTPException(400, "Merge requires at least 2 items")

    # Build merge feedback from selected items
    parts = []
    if req.level == "concept":
        if not s.get("concepts"):
            raise HTTPException(400, "No concepts to merge")
        for idx in req.indices:
            c = s["concepts"][idx]
            parts.append(f"方案{idx+1}「{c.title}」: {c.description}")
    elif req.level == "direction":
        cb = _get_concept_branch(s, req.concept_index)
        if not cb.get("directions"):
            raise HTTPException(400, "No directions to merge")
        for idx in req.indices:
            d = cb["directions"][idx]
            parts.append(f"方案{idx+1}「{d.title}」: {d.description}")
    elif req.level == "script":
        cb = _get_concept_branch(s, req.concept_index)
        db = _get_direction_branch(cb, req.direction_index)
        if not db.get("scripts"):
            raise HTTPException(400, "No scripts to merge")
        for idx in req.indices:
            sc = db["scripts"][idx]
            parts.append(f"方案{idx+1}「{sc.outline[:60]}」")
    else:
        raise HTTPException(400, f"Invalid level: {req.level}")

    merge_feedback = (
        "请融合以下方案的优点，生成新方案：\n"
        + "\n".join(parts)
        + f"\n用户指令：{req.instruction}"
    )

    # Regenerate with merge feedback
    if req.level == "concept":
        gen = ConceptGenerator()
        async with llm_semaphore:
            result = await asyncio.to_thread(
                gen.generate, s["goal"], s["brand_kb"], s["insights"], merge_feedback
            )
        s["concepts"] = result.concepts
        s["selected_concept_indices"] = None
        s["branches"] = None
        _save_campaign(cid)
        return {
            "concepts": [
                {"id": c.id, "title": c.title, "description": c.description, "rationale": c.rationale}
                for c in result.concepts
            ]
        }
    elif req.level == "direction":
        cb = _get_concept_branch(s, req.concept_index)
        concept = s["concepts"][req.concept_index]
        gen = DirectionGenerator()
        async with llm_semaphore:
            result = await asyncio.to_thread(
                gen.generate, s["goal"], s["brand_kb"], concept, merge_feedback,
                platform_kb=s["platform_kb"],
            )
        cb["directions"] = result.directions
        cb["selected_direction_indices"] = None
        cb["direction_branches"] = None
        _save_campaign(cid)
        return {
            "concept_index": req.concept_index,
            "directions": [
                {"id": d.id, "title": d.title, "description": d.description, "platform_notes": d.platform_notes}
                for d in result.directions
            ],
        }
    else:  # script
        cb = _get_concept_branch(s, req.concept_index)
        db = _get_direction_branch(cb, req.direction_index)
        direction = cb["directions"][req.direction_index]
        gen = ScriptGenerator()
        async with llm_semaphore:
            result = await asyncio.to_thread(
                gen.generate, s["goal"], s["brand_kb"], direction, feedback=merge_feedback,
                platform_kb=s["platform_kb"],
            )
        db["scripts"] = result.scripts
        db["selected_script_indices"] = None
        db["script_branches"] = None
        _save_campaign(cid)
        return {
            "concept_index": req.concept_index,
            "direction_index": req.direction_index,
            "scripts": [_serialize_script(sc) for sc in result.scripts],
        }


# ── Tree visualization ──


@app.get("/api/campaigns/{cid}/tree")
async def campaign_tree(cid: str):
    """Return tree structure for visualization."""
    s = _get(cid)
    goal = s["goal"]
    nodes = {}
    active_path = []

    # Root
    root_id = "root"
    nodes[root_id] = {
        "node_id": root_id, "node_type": "root", "status": "selected",
        "parent_id": None, "children": [],
        "data": {"brand_name": s["brand_kb"].name, "objective": goal.objective, "platform": goal.platform},
        "feedback": "", "created_at": "",
    }
    active_path.append(root_id)

    # Concepts
    if s.get("concepts"):
        selected_cis = set(s.get("selected_concept_indices") or [])
        for i, c in enumerate(s["concepts"]):
            nid = f"c{i}"
            status = "selected" if i in selected_cis else "generated"
            nodes[nid] = {
                "node_id": nid, "node_type": "concept", "status": status,
                "parent_id": root_id, "children": [],
                "data": {"id": c.id, "title": c.title, "description": c.description, "rationale": c.rationale},
                "feedback": "", "created_at": "",
            }
            nodes[root_id]["children"].append(nid)

    # Branches: directions, scripts, images
    for cb in (s.get("branches") or []):
        ci = cb["concept_index"]
        c_nid = f"c{ci}"
        if c_nid not in nodes:
            continue
        selected_dis = set(cb.get("selected_direction_indices") or [])
        if cb.get("directions"):
            for j, d in enumerate(cb["directions"]):
                d_nid = f"c{ci}_d{j}"
                status = "selected" if j in selected_dis else "generated"
                nodes[d_nid] = {
                    "node_id": d_nid, "node_type": "direction", "status": status,
                    "parent_id": c_nid, "children": [],
                    "data": {"id": d.id, "title": d.title, "description": d.description, "platform_notes": d.platform_notes},
                    "feedback": "", "created_at": "",
                }
                nodes[c_nid]["children"].append(d_nid)

        for db in (cb.get("direction_branches") or []):
            di = db["direction_index"]
            d_nid = f"c{ci}_d{di}"
            if d_nid not in nodes:
                continue
            selected_sis = set(db.get("selected_script_indices") or [])
            if db.get("scripts"):
                for k, sc in enumerate(db["scripts"]):
                    s_nid = f"c{ci}_d{di}_s{k}"
                    status = "selected" if k in selected_sis else "generated"
                    nodes[s_nid] = {
                        "node_id": s_nid, "node_type": "script", "status": status,
                        "parent_id": d_nid, "children": [],
                        "data": {"id": sc.id, "outline": sc.outline, "visual_style": sc.visual_style},
                        "feedback": "", "created_at": "",
                    }
                    nodes[d_nid]["children"].append(s_nid)

            for sb in (db.get("script_branches") or []):
                si = sb["script_index"]
                s_nid = f"c{ci}_d{di}_s{si}"
                if s_nid not in nodes:
                    continue
                if sb.get("images"):
                    img_nid = f"c{ci}_d{di}_s{si}_img"
                    nodes[img_nid] = {
                        "node_id": img_nid, "node_type": "images", "status": "selected",
                        "parent_id": s_nid, "children": [],
                        "data": {
                            "visual_style": sb.get("confirmed_style", ""),
                            "images": [{"scene_no": img.scene_no, "image_path": img.image_path.replace("\\", "/")} for img in sb["images"]],
                        },
                        "feedback": "", "created_at": "",
                    }
                    nodes[s_nid]["children"].append(img_nid)

    # Build active_path from first selected at each level
    def _walk_active(node_id):
        active_path.append(node_id)
        node = nodes[node_id]
        for child_id in node["children"]:
            child = nodes[child_id]
            if child["status"] == "selected":
                _walk_active(child_id)
                return

    if nodes[root_id]["children"]:
        for child_id in nodes[root_id]["children"]:
            if nodes[child_id]["status"] == "selected":
                _walk_active(child_id)
                break

    return {
        "campaign_id": cid,
        "brand_id": goal.brand_id,
        "objective": goal.objective,
        "platform": goal.platform,
        "notes": goal.notes,
        "root_id": root_id,
        "active_path": active_path,
        "nodes": nodes,
    }


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
app.mount("/brands", StaticFiles(directory="brands"), name="brands")


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

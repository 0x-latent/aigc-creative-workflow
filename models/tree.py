"""Creative Tree data model — persistent tree structure for campaign exploration."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _new_node_id() -> str:
    return f"n_{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TreeNode:
    node_id: str
    node_type: str  # "root" | "concept" | "direction" | "script" | "images"
    status: str  # "generated" | "selected" | "rejected"
    parent_id: str | None
    children: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    meta: dict | None = None
    feedback: str = ""
    created_at: str = field(default_factory=_now_iso)


@dataclass
class CampaignTree:
    campaign_id: str
    brand_id: str
    objective: str
    platform: str
    notes: str
    created_at: str
    updated_at: str
    nodes: dict[str, TreeNode] = field(default_factory=dict)
    root_id: str = ""
    active_path: list[str] = field(default_factory=list)
    version: int = 1

    # ── Factory ────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        campaign_id: str,
        brand_id: str,
        objective: str,
        platform: str,
        notes: str = "",
        root_data: dict | None = None,
    ) -> CampaignTree:
        now = _now_iso()
        root = TreeNode(
            node_id=_new_node_id(),
            node_type="root",
            status="selected",
            parent_id=None,
            data=root_data or {},
            created_at=now,
        )
        tree = cls(
            campaign_id=campaign_id,
            brand_id=brand_id,
            objective=objective,
            platform=platform,
            notes=notes,
            created_at=now,
            updated_at=now,
            root_id=root.node_id,
            active_path=[root.node_id],
        )
        tree.nodes[root.node_id] = root
        return tree

    # ── Persistence ────────────────────────────────────────────

    def save(self, output_dir: str = "output") -> str:
        self.updated_at = _now_iso()
        path = os.path.join(output_dir, self.campaign_id, "campaign_tree.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "version": self.version,
            "campaign_id": self.campaign_id,
            "brand_id": self.brand_id,
            "objective": self.objective,
            "platform": self.platform,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "root_id": self.root_id,
            "active_path": self.active_path,
            "nodes": {nid: asdict(node) for nid, node in self.nodes.items()},
        }
        # Atomic write: tmp → rename
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return path

    @classmethod
    def load(cls, campaign_id: str, output_dir: str = "output") -> CampaignTree:
        path = os.path.join(output_dir, campaign_id, "campaign_tree.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        nodes: dict[str, TreeNode] = {}
        for nid, nd in data["nodes"].items():
            nodes[nid] = TreeNode(
                node_id=nd["node_id"],
                node_type=nd["node_type"],
                status=nd["status"],
                parent_id=nd.get("parent_id"),
                children=nd.get("children", []),
                data=nd.get("data", {}),
                meta=nd.get("meta"),
                feedback=nd.get("feedback", ""),
                created_at=nd.get("created_at", ""),
            )
        return cls(
            campaign_id=data["campaign_id"],
            brand_id=data["brand_id"],
            objective=data["objective"],
            platform=data["platform"],
            notes=data["notes"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            nodes=nodes,
            root_id=data["root_id"],
            active_path=data.get("active_path", []),
            version=data.get("version", 1),
        )

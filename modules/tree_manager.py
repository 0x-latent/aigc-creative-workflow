"""TreeManager — manipulation, navigation and display for CampaignTree."""

from __future__ import annotations

from dataclasses import asdict

from models.tree import CampaignTree, TreeNode, _new_node_id, _now_iso

# Next step after a given node type
_NEXT_STEP: dict[str, str] = {
    "root": "concept",
    "concept": "direction",
    "direction": "script",
    "script": "images",
    "images": "",  # terminal
}

# Display labels
_TYPE_LABEL: dict[str, str] = {
    "root": "根",
    "concept": "概念",
    "direction": "方向",
    "script": "脚本",
    "images": "图片",
}

_STATUS_BADGE: dict[str, str] = {
    "selected": "S",
    "generated": "G",
    "rejected": "R",
}


class TreeManager:
    def __init__(self, tree: CampaignTree):
        self.tree = tree

    # ── Mutation ───────────────────────────────────────────────

    def add_generation_batch(
        self,
        parent_id: str,
        node_type: str,
        items: list[dict],
        meta: dict | None = None,
        feedback: str = "",
    ) -> list[str]:
        """Store N generated items as children of *parent_id*. Returns node_ids."""
        parent = self.tree.nodes[parent_id]
        node_ids: list[str] = []
        now = _now_iso()
        for item in items:
            nid = _new_node_id()
            node = TreeNode(
                node_id=nid,
                node_type=node_type,
                status="generated",
                parent_id=parent_id,
                data=item,
                meta=meta,
                feedback=feedback,
                created_at=now,
            )
            self.tree.nodes[nid] = node
            parent.children.append(nid)
            node_ids.append(nid)
        return node_ids

    def select_node(self, node_id: str):
        """Mark a node as selected and rebuild active_path from root."""
        self.tree.nodes[node_id].status = "selected"
        # Rebuild active_path: walk from this node up to root, then reverse
        chain = []
        cur = node_id
        while cur is not None:
            chain.append(cur)
            cur = self.tree.nodes[cur].parent_id
        chain.reverse()
        self.tree.active_path = chain

    def reject_batch(self, node_ids: list[str], feedback: str = ""):
        """Mark a batch of nodes as rejected."""
        for nid in node_ids:
            node = self.tree.nodes[nid]
            node.status = "rejected"
            if feedback:
                node.feedback = feedback

    # ── Query ──────────────────────────────────────────────────

    def get_node(self, node_id: str) -> TreeNode:
        return self.tree.nodes[node_id]

    def get_children(
        self, node_id: str, node_type: str | None = None
    ) -> list[TreeNode]:
        parent = self.tree.nodes[node_id]
        children = [self.tree.nodes[cid] for cid in parent.children]
        if node_type:
            children = [c for c in children if c.node_type == node_type]
        return children

    def get_selected_child(
        self, node_id: str, node_type: str | None = None
    ) -> TreeNode | None:
        for child in self.get_children(node_id, node_type):
            if child.status == "selected":
                return child
        return None

    def get_ancestor_chain(self, node_id: str) -> list[TreeNode]:
        """Walk from node up to root (inclusive), returned root-first."""
        chain: list[TreeNode] = []
        cur: str | None = node_id
        while cur is not None:
            chain.append(self.tree.nodes[cur])
            cur = self.tree.nodes[cur].parent_id
        chain.reverse()
        return chain

    def get_branch_point_context(self, node_id: str) -> dict:
        """Extract the concept/direction/script context from ancestors.

        Returns a dict like:
            {"concept": {data}, "direction": {data}, "script": {data}}
        keyed by node_type.  Only includes ancestors that exist in the chain.
        """
        chain = self.get_ancestor_chain(node_id)
        ctx: dict = {}
        for node in chain:
            if node.node_type != "root":
                ctx[node.node_type] = node.data
        return ctx

    def find_resume_point(self) -> tuple[str, str]:
        """Walk active_path to find the deepest selected node.

        Returns (node_id, next_step_type).  If the tree is complete
        (images selected), next_step_type is empty string.
        """
        if not self.tree.active_path:
            return self.tree.root_id, "concept"

        deepest_id = self.tree.active_path[-1]
        deepest = self.tree.nodes[deepest_id]
        next_step = _NEXT_STEP.get(deepest.node_type, "")
        return deepest_id, next_step

    # ── Display ────────────────────────────────────────────────

    def _node_label(self, node: TreeNode) -> str:
        badge = _STATUS_BADGE.get(node.status, "?")
        type_label = _TYPE_LABEL.get(node.node_type, node.node_type)
        title = node.data.get("title") or node.data.get("outline") or node.data.get("brand_name") or ""
        if node.node_type == "images":
            count = len(node.data.get("images", []))
            title = f"{count}张图片"
        if node.node_type == "root":
            title = f"{self.tree.brand_id} / {self.tree.platform}"
        short_id = node.node_id
        if title:
            return f"[{badge}] {short_id} {type_label}: {title}"
        return f"[{badge}] {short_id} {type_label}"

    def print_ascii_tree(self, highlight_path: list[str] | None = None):
        """Print the tree to stdout with ASCII art."""
        if highlight_path is None:
            highlight_path = self.tree.active_path

        def _print(node_id: str, prefix: str, is_last: bool):
            node = self.tree.nodes[node_id]
            connector = "└── " if is_last else "├── "
            marker = " ★" if node_id in highlight_path else ""
            print(f"{prefix}{connector}{self._node_label(node)}{marker}")

            child_prefix = prefix + ("    " if is_last else "│   ")
            children = [self.tree.nodes[cid] for cid in node.children]
            for i, child in enumerate(children):
                _print(child.node_id, child_prefix, i == len(children) - 1)

        root = self.tree.nodes[self.tree.root_id]
        print(f"\n{'═'*60}")
        print(f"  创意树 — {self.tree.campaign_id}")
        print(f"{'═'*60}")
        marker = " ★" if self.tree.root_id in highlight_path else ""
        print(f"  {self._node_label(root)}{marker}")
        children = [self.tree.nodes[cid] for cid in root.children]
        for i, child in enumerate(children):
            _print(child.node_id, "  ", i == len(children) - 1)
        print()

    def print_node_detail(self, node_id: str):
        """Print detailed info for a single node."""
        node = self.tree.nodes[node_id]
        type_label = _TYPE_LABEL.get(node.node_type, node.node_type)
        print(f"\n{'─'*60}")
        print(f"  节点详情: {node.node_id} ({type_label})")
        print(f"  状态: {node.status}")
        print(f"  创建时间: {node.created_at}")
        if node.feedback:
            print(f"  反馈: {node.feedback}")
        print(f"{'─'*60}")

        data = node.data
        if node.node_type == "concept":
            print(f"  标题: {data.get('title', '')}")
            print(f"  描述: {data.get('description', '')}")
            print(f"  推导: {data.get('rationale', '')}")
        elif node.node_type == "direction":
            print(f"  标题: {data.get('title', '')}")
            print(f"  描述: {data.get('description', '')}")
            print(f"  平台适配: {data.get('platform_notes', '')}")
        elif node.node_type == "script":
            print(f"  大纲: {data.get('outline', '')}")
            print(f"  视觉风格: {data.get('visual_style', '')}")
            scenes = data.get("scenes", [])
            for s in scenes:
                print(f"    场景{s.get('scene_no', '?')}: {s.get('visual_description', '')}")
                print(f"      旁白: {s.get('voiceover', '')}")
        elif node.node_type == "images":
            for img in data.get("images", []):
                print(f"  场景{img.get('scene_no', '?')}: {img.get('image_path', '')}")
        elif node.node_type == "root":
            print(f"  品牌: {data.get('brand_name', self.tree.brand_id)}")
            print(f"  目标: {self.tree.objective}")
            print(f"  平台: {self.tree.platform}")
        print()

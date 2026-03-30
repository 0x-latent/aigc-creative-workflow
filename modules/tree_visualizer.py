"""TreeVisualizer — generates a self-contained HTML file for the creative tree."""

from __future__ import annotations

import json
import os

from models.tree import CampaignTree

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Creative Tree — {campaign_id}</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background: #0f1117; color: #e0e0e0; display: flex; height: 100vh; overflow: hidden; }
#sidebar { width: 380px; min-width: 380px; background: #1a1d27; border-right: 1px solid #2a2d3a; display: flex; flex-direction: column; overflow: hidden; }
#sidebar-header { padding: 16px 20px; border-bottom: 1px solid #2a2d3a; }
#sidebar-header h2 { font-size: 14px; color: #888; margin-bottom: 4px; }
#sidebar-header h1 { font-size: 18px; color: #fff; }
#sidebar-header .meta { font-size: 12px; color: #666; margin-top: 8px; }
#controls { padding: 12px 20px; border-bottom: 1px solid #2a2d3a; display: flex; gap: 8px; flex-wrap: wrap; }
#controls button { padding: 4px 12px; border: 1px solid #3a3d4a; border-radius: 4px; background: transparent; color: #aaa; cursor: pointer; font-size: 12px; }
#controls button:hover { background: #2a2d3a; color: #fff; }
#controls button.active { background: #2563eb; border-color: #2563eb; color: #fff; }
#search { padding: 4px 12px; border: 1px solid #3a3d4a; border-radius: 4px; background: #0f1117; color: #e0e0e0; font-size: 12px; flex: 1; min-width: 120px; }
#tree-container { flex: 1; overflow: auto; padding: 24px; }
#detail-panel { width: 420px; min-width: 420px; background: #1a1d27; border-left: 1px solid #2a2d3a; overflow-y: auto; display: none; }
#detail-panel.open { display: block; }
#detail-close { position: absolute; top: 12px; right: 12px; background: none; border: none; color: #888; cursor: pointer; font-size: 18px; }
#detail-content { padding: 20px; position: relative; }
#detail-content h2 { font-size: 16px; color: #fff; margin-bottom: 16px; padding-right: 30px; }
.detail-section { margin-bottom: 16px; }
.detail-section h3 { font-size: 12px; color: #888; text-transform: uppercase; margin-bottom: 6px; }
.detail-section p, .detail-section pre { font-size: 13px; color: #ccc; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.detail-section .scene-card { background: #0f1117; border-radius: 6px; padding: 10px 12px; margin-bottom: 8px; border-left: 3px solid #3a3d4a; }
.detail-section .scene-card .scene-no { font-size: 11px; color: #666; margin-bottom: 4px; }
.thumb-gallery { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.thumb-gallery img { width: 120px; height: 80px; object-fit: cover; border-radius: 4px; border: 1px solid #2a2d3a; cursor: pointer; }
.thumb-gallery img:hover { border-color: #2563eb; }

/* Tree layout */
.tree-root { list-style: none; padding-left: 0; }
.tree-list { list-style: none; padding-left: 28px; position: relative; }
.tree-list::before { content: ''; position: absolute; left: 13px; top: 0; bottom: 12px; width: 1px; background: #2a2d3a; }
.tree-item { position: relative; padding: 3px 0; }
.tree-item::before { content: ''; position: absolute; left: -15px; top: 14px; width: 15px; height: 1px; background: #2a2d3a; }
.tree-root > .tree-item::before { display: none; }

.tree-node { display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 6px; border: 1.5px solid #2a2d3a; background: #1e2130; cursor: pointer; transition: all 0.15s; max-width: 500px; }
.tree-node:hover { border-color: #4a4d5a; background: #252838; }
.tree-node.status-selected { border-color: #22c55e; background: #0f2a1a; }
.tree-node.status-rejected { border-color: #666; background: #1a1a1a; opacity: 0.5; }
.tree-node.status-generated { border-color: #3b82f6; background: #0f1a2e; }
.tree-node.active-path { box-shadow: 0 0 0 2px #f59e0b44, 0 0 8px #f59e0b22; }
.tree-node.highlight { border-color: #f59e0b; }

.node-badge { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.badge-selected { background: #22c55e; }
.badge-rejected { background: #ef4444; }
.badge-generated { background: #3b82f6; }

.node-type { font-size: 10px; color: #888; background: #2a2d3a; padding: 1px 6px; border-radius: 3px; flex-shrink: 0; }
.node-title { font-size: 13px; color: #e0e0e0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-id { font-size: 10px; color: #555; flex-shrink: 0; font-family: monospace; }

.collapse-btn { background: none; border: none; color: #666; cursor: pointer; font-size: 12px; padding: 0 4px; flex-shrink: 0; }
.collapse-btn:hover { color: #fff; }
.tree-list.collapsed { display: none; }
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-header">
    <h2>CREATIVE TREE</h2>
    <h1 id="campaign-title"></h1>
    <div class="meta" id="campaign-meta"></div>
  </div>
  <div id="controls">
    <button onclick="expandAll()">展开全部</button>
    <button onclick="collapseAll()">折叠全部</button>
    <button id="btn-path" onclick="togglePathOnly()">仅选中路径</button>
    <input type="text" id="search" placeholder="搜索节点..." oninput="searchNodes(this.value)">
  </div>
  <div id="tree-container"></div>
</div>

<div id="detail-panel">
  <div id="detail-content">
    <button id="detail-close" onclick="closeDetail()">&times;</button>
    <h2 id="detail-title"></h2>
    <div id="detail-body"></div>
  </div>
</div>

<script>
const TREE_DATA = __TREE_JSON__;
const ACTIVE_PATH = new Set(TREE_DATA.active_path || []);
const nodes = TREE_DATA.nodes;

const TYPE_LABELS = {root: '根', concept: '概念', direction: '方向', script: '脚本', images: '图片'};
let pathOnlyMode = false;

function getTitle(node) {
  const d = node.data || {};
  if (node.node_type === 'root') return (d.brand_name || TREE_DATA.brand_id) + ' / ' + TREE_DATA.platform;
  if (node.node_type === 'images') return (d.images || []).length + '张图片';
  return d.title || d.outline || d.id || node.node_id;
}

function buildTree(nodeId) {
  const node = nodes[nodeId];
  if (!node) return '';
  const children = node.children || [];
  const isActive = ACTIVE_PATH.has(nodeId);
  const badgeClass = 'badge-' + node.status;
  const nodeClasses = ['tree-node', 'status-' + node.status];
  if (isActive) nodeClasses.push('active-path');

  let childrenHtml = '';
  if (children.length > 0) {
    const childItems = children.map(cid => '<li class="tree-item">' + buildTree(cid) + '</li>').join('');
    childrenHtml = '<ul class="tree-list">' + childItems + '</ul>';
  }

  const collapseBtn = children.length > 0
    ? '<button class="collapse-btn" onclick="toggleCollapse(event, this)">&#9660;</button>'
    : '';

  return '<div class="' + nodeClasses.join(' ') + '" data-id="' + nodeId + '" onclick="showDetail(\'' + nodeId + '\')">'
    + '<span class="node-badge ' + badgeClass + '"></span>'
    + '<span class="node-type">' + (TYPE_LABELS[node.node_type] || node.node_type) + '</span>'
    + '<span class="node-title">' + escapeHtml(getTitle(node)) + '</span>'
    + '<span class="node-id">' + nodeId + '</span>'
    + collapseBtn
    + '</div>'
    + childrenHtml;
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function render() {
  const container = document.getElementById('tree-container');
  container.innerHTML = '<ul class="tree-root"><li class="tree-item">' + buildTree(TREE_DATA.root_id) + '</li></ul>';
  document.getElementById('campaign-title').textContent = TREE_DATA.brand_id + ' — ' + TREE_DATA.objective;
  document.getElementById('campaign-meta').textContent =
    '平台: ' + TREE_DATA.platform + '  |  ID: ' + TREE_DATA.campaign_id +
    '\n创建: ' + (TREE_DATA.created_at || '').slice(0, 10);
}

function toggleCollapse(e, btn) {
  e.stopPropagation();
  const ul = btn.closest('.tree-node').nextElementSibling;
  if (ul && ul.classList.contains('tree-list')) {
    ul.classList.toggle('collapsed');
    btn.innerHTML = ul.classList.contains('collapsed') ? '&#9654;' : '&#9660;';
  }
}

function expandAll() {
  document.querySelectorAll('.tree-list.collapsed').forEach(el => el.classList.remove('collapsed'));
  document.querySelectorAll('.collapse-btn').forEach(btn => btn.innerHTML = '&#9660;');
}

function collapseAll() {
  document.querySelectorAll('.tree-list').forEach(el => el.classList.add('collapsed'));
  document.querySelectorAll('.collapse-btn').forEach(btn => btn.innerHTML = '&#9654;');
}

function togglePathOnly() {
  pathOnlyMode = !pathOnlyMode;
  document.getElementById('btn-path').classList.toggle('active', pathOnlyMode);
  document.querySelectorAll('.tree-item').forEach(item => {
    const nodeEl = item.querySelector('.tree-node');
    if (!nodeEl) return;
    const id = nodeEl.dataset.id;
    if (pathOnlyMode && !ACTIVE_PATH.has(id)) {
      item.style.display = 'none';
    } else {
      item.style.display = '';
    }
  });
}

function searchNodes(query) {
  query = query.toLowerCase().trim();
  document.querySelectorAll('.tree-node').forEach(el => {
    el.classList.remove('highlight');
    if (query && el.textContent.toLowerCase().includes(query)) {
      el.classList.add('highlight');
      // expand parents
      let parent = el.closest('.tree-list.collapsed');
      while (parent) {
        parent.classList.remove('collapsed');
        parent = parent.parentElement ? parent.parentElement.closest('.tree-list.collapsed') : null;
      }
    }
  });
}

function showDetail(nodeId) {
  const node = nodes[nodeId];
  if (!node) return;
  const panel = document.getElementById('detail-panel');
  panel.classList.add('open');

  const typeLabel = TYPE_LABELS[node.node_type] || node.node_type;
  document.getElementById('detail-title').textContent = typeLabel + ': ' + getTitle(node);

  let html = '';
  html += '<div class="detail-section"><h3>状态</h3><p>' + node.status + '</p></div>';
  html += '<div class="detail-section"><h3>节点 ID</h3><p style="font-family:monospace;user-select:all">' + nodeId + '</p></div>';
  html += '<div class="detail-section"><h3>创建时间</h3><p>' + (node.created_at || '') + '</p></div>';
  if (node.feedback) {
    html += '<div class="detail-section"><h3>反馈</h3><p>' + escapeHtml(node.feedback) + '</p></div>';
  }

  const d = node.data || {};

  if (node.node_type === 'concept') {
    html += sec('标题', d.title);
    html += sec('描述', d.description);
    html += sec('推导依据', d.rationale);
  } else if (node.node_type === 'direction') {
    html += sec('标题', d.title);
    html += sec('描述', d.description);
    html += sec('平台适配', d.platform_notes);
  } else if (node.node_type === 'script') {
    html += sec('大纲', d.outline);
    html += sec('视觉风格', d.visual_style);
    if (d.scenes) {
      html += '<div class="detail-section"><h3>场景 (' + d.scenes.length + ')</h3>';
      d.scenes.forEach(s => {
        html += '<div class="scene-card">'
          + '<div class="scene-no">场景 ' + s.scene_no + (s.page_type ? ' (' + s.page_type + ')' : '') + '</div>'
          + '<p><strong>画面:</strong> ' + escapeHtml(s.visual_description || '') + '</p>'
          + '<p><strong>旁白:</strong> ' + escapeHtml(s.voiceover || '') + '</p>'
          + '<p style="font-size:11px;color:#666"><strong>Image Prompt:</strong> ' + escapeHtml(s.image_prompt || '') + '</p>'
          + '</div>';
      });
      html += '</div>';
    }
  } else if (node.node_type === 'images') {
    html += sec('视觉风格', d.visual_style);
    if (d.images) {
      html += '<div class="detail-section"><h3>图片 (' + d.images.length + ')</h3><div class="thumb-gallery">';
      d.images.forEach(img => {
        const src = img.image_path || '';
        html += '<div style="margin-bottom:8px">'
          + '<img src="' + escapeHtml(src) + '" onerror="this.style.display=\'none\'" alt="scene ' + img.scene_no + '">'
          + '<div style="font-size:11px;color:#666">场景 ' + img.scene_no + '</div>'
          + '</div>';
      });
      html += '</div></div>';
    }
  } else if (node.node_type === 'root') {
    html += sec('品牌', d.brand_name || TREE_DATA.brand_id);
    html += sec('目标', TREE_DATA.objective);
    html += sec('平台', TREE_DATA.platform);
    if (TREE_DATA.notes) html += sec('备注', TREE_DATA.notes);
  }

  document.getElementById('detail-body').innerHTML = html;
}

function sec(title, content) {
  if (!content) return '';
  return '<div class="detail-section"><h3>' + title + '</h3><p>' + escapeHtml(content) + '</p></div>';
}

function closeDetail() {
  document.getElementById('detail-panel').classList.remove('open');
}

render();
</script>
</body>
</html>"""


class TreeVisualizer:
    def generate_html(self, tree: CampaignTree, output_dir: str = "output") -> str:
        """Generate a self-contained HTML visualization. Returns file path."""
        # Serialize tree for embedding
        tree_dict = {
            "campaign_id": tree.campaign_id,
            "brand_id": tree.brand_id,
            "objective": tree.objective,
            "platform": tree.platform,
            "notes": tree.notes,
            "created_at": tree.created_at,
            "updated_at": tree.updated_at,
            "root_id": tree.root_id,
            "active_path": tree.active_path,
            "nodes": {},
        }
        for nid, node in tree.nodes.items():
            tree_dict["nodes"][nid] = {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "status": node.status,
                "parent_id": node.parent_id,
                "children": node.children,
                "data": node.data,
                "feedback": node.feedback,
                "created_at": node.created_at,
            }

        tree_json = json.dumps(tree_dict, ensure_ascii=False, indent=2)
        html = _HTML_TEMPLATE.replace("{campaign_id}", tree.campaign_id)
        html = html.replace("__TREE_JSON__", tree_json)

        out_path = os.path.join(output_dir, tree.campaign_id, "creative_tree.html")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        return out_path

# Generate graphify-out/graph3d.html (rotatable 3D view) from the data
# already embedded in graphify-out/graph.html.
import json
import re

SRC = r"D:/GIT REPO MAIN/qpg/graphify-out/graph.html"
DST = r"D:/GIT REPO MAIN/qpg/graphify-out/graph3d.html"

src = open(SRC, encoding="utf-8").read()
raw_nodes = json.loads(re.search(r"const RAW_NODES = (\[.*?\]);", src).group(1))
raw_edges = json.loads(re.search(r"const RAW_EDGES = (\[.*?\]);", src).group(1))
legend = json.loads(re.search(r"const LEGEND = (\[.*?\]);", src).group(1))

nodes = [
    {
        "id": n["id"],
        "label": n["label"],
        "color": n["color"]["background"],
        "size": n["size"],
        "community": n["community"],
        "community_name": n["community_name"],
        "source_file": n.get("source_file") or "",
        "file_type": n.get("file_type") or "",
        "degree": n.get("degree", 0),
    }
    for n in raw_nodes
]
links = [
    {
        "source": e["from"],
        "target": e["to"],
        "relation": e.get("label") or "",
        "title": e.get("title") or "",
        "confidence": e.get("confidence") or "",
    }
    for e in raw_edges
]

def js(obj):
    # escape "</" so no string can terminate the <script> block
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

stats = f"{len(nodes)} nodes &middot; {len(links)} edges &middot; {len(legend)} communities"

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>graphify 3D - graphify-out\graph3d.html</title>
<script src="https://unpkg.com/3d-force-graph@1/dist/3d-force-graph.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; display: flex; height: 100vh; overflow: hidden; }
  #graph { flex: 1; min-width: 0; position: relative; overflow: hidden; }
  #controls { position: fixed; top: 12px; left: 12px; z-index: 10; display: flex; gap: 8px; align-items: center; }
  #controls button, #controls a { background: #1a1a2eE6; border: 1px solid #3a3a5e; color: #ccc; padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; text-decoration: none; display: inline-block; }
  #controls button:hover, #controls a:hover { border-color: #4E79A7; color: #fff; }
  #controls button.active { background: #4E79A7; border-color: #4E79A7; color: #fff; }
  #hint { position: fixed; bottom: 10px; left: 12px; z-index: 10; font-size: 11px; color: #667; pointer-events: none; }
  #sidebar { width: 280px; flex-shrink: 0; background: #1a1a2e; border-left: 1px solid #2a2a4e; display: flex; flex-direction: column; overflow: hidden; }
  #search-wrap { padding: 12px; border-bottom: 1px solid #2a2a4e; }
  #search { width: 100%; background: #0f0f1a; border: 1px solid #3a3a5e; color: #e0e0e0; padding: 7px 10px; border-radius: 6px; font-size: 13px; outline: none; }
  #search:focus { border-color: #4E79A7; }
  #search-results { max-height: 140px; overflow-y: auto; padding: 4px 12px; border-bottom: 1px solid #2a2a4e; display: none; }
  .search-item { padding: 4px 6px; cursor: pointer; border-radius: 4px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .search-item:hover { background: #2a2a4e; }
  #info-panel { padding: 14px; border-bottom: 1px solid #2a2a4e; min-height: 140px; }
  #info-panel h3 { font-size: 13px; color: #aaa; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em; }
  #info-content { font-size: 13px; color: #ccc; line-height: 1.6; }
  #info-content .field { margin-bottom: 5px; }
  #info-content .field b { color: #e0e0e0; }
  #info-content .empty { color: #555; font-style: italic; }
  .neighbor-link { display: block; padding: 2px 6px; margin: 2px 0; border-radius: 3px; cursor: pointer; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-left: 3px solid #333; }
  .neighbor-link:hover { background: #2a2a4e; }
  #neighbors-list { max-height: 160px; overflow-y: auto; margin-top: 4px; }
  #legend-wrap { flex: 1; overflow-y: auto; padding: 12px; }
  #legend-wrap h3 { font-size: 13px; color: #aaa; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
  .legend-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer; border-radius: 4px; font-size: 12px; }
  .legend-item:hover { background: #2a2a4e; padding-left: 4px; }
  .legend-item.dimmed { opacity: 0.35; }
  .legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
  .legend-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .legend-count { color: #666; font-size: 11px; }
  #stats { padding: 10px 14px; border-top: 1px solid #2a2a4e; font-size: 11px; color: #555; }
  #legend-controls { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; padding: 4px 0; }
  #legend-controls label { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #aaa; cursor: pointer; }
  #legend-controls label:hover { color: #e0e0e0; }
  .legend-cb, #select-all-cb { appearance: none; -webkit-appearance: none; width: 14px; height: 14px; border: 1.5px solid #3a3a5e; border-radius: 3px; background: #0f0f1a; cursor: pointer; position: relative; flex-shrink: 0; }
  .legend-cb:checked, #select-all-cb:checked { background: #4E79A7; border-color: #4E79A7; }
  .legend-cb:checked::after, #select-all-cb:checked::after { content: ''; position: absolute; left: 3.5px; top: 1px; width: 4px; height: 7px; border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg); }
  #select-all-cb:indeterminate { background: #4E79A7; border-color: #4E79A7; }
  #select-all-cb:indeterminate::after { content: ''; position: absolute; left: 2px; top: 5px; width: 8px; height: 2px; background: #fff; border: none; transform: none; }
  .graph-tooltip { font-family: inherit !important; }
</style>
</head>
<body>
<div id="graph"></div>
<div id="controls">
  <button id="rotate-btn" onclick="toggleAutoRotate()">Auto-rotate</button>
  <button onclick="resetView()">Reset view</button>
  <a href="graph.html" title="Back to the flat 2D view">2D view</a>
</div>
<div id="hint">drag: rotate (all axes) &middot; right-drag: pan &middot; scroll: zoom</div>
<div id="sidebar">
  <div id="search-wrap">
    <input id="search" type="text" placeholder="Search nodes..." autocomplete="off">
    <div id="search-results"></div>
  </div>
  <div id="info-panel">
    <h3>Node Info</h3>
    <div id="info-content"><span class="empty">Click a node to inspect it</span></div>
  </div>
  <div id="legend-wrap">
    <h3>Communities</h3>
    <div id="legend-controls">
      <label><input type="checkbox" id="select-all-cb" checked onchange="toggleAllCommunities(!this.checked)">Select All</label>
    </div>
    <div id="legend"></div>
  </div>
  <div id="stats">__STATS__</div>
</div>
<script>
const NODES = __NODES__;
const LINKS = __LINKS__;
const LEGEND = __LEGEND__;

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

const nodeById = new Map(NODES.map(n => [n.id, n]));
const communityColor = new Map(LEGEND.map(l => [l.cid, l.color]));

// Capture endpoint ids before ForceGraph3D replaces source/target with object refs
const adjacency = new Map(); // id -> [{otherId, relation, out, link}]
LINKS.forEach(l => {
  l._s = l.source; l._t = l.target;
  if (!adjacency.has(l._s)) adjacency.set(l._s, []);
  if (!adjacency.has(l._t)) adjacency.set(l._t, []);
  adjacency.get(l._s).push({ otherId: l._t, relation: l.relation, out: true, link: l });
  adjacency.get(l._t).push({ otherId: l._s, relation: l.relation, out: false, link: l });
});

const hiddenCommunities = new Set();
let selectedId = null;
const highlightNodes = new Set();
const highlightLinks = new Set();

const graphEl = document.getElementById('graph');
const Graph = ForceGraph3D({ controlType: 'trackball' })(graphEl)
  .backgroundColor('#0f0f1a')
  .width(graphEl.clientWidth)
  .height(graphEl.clientHeight)
  .nodeLabel(n => '<b>' + esc(n.label) + '</b><br>' + esc(n.community_name) +
                  (n.source_file ? '<br><span style="color:#889">' + esc(n.source_file) + '</span>' : ''))
  .nodeColor(n => {
    if (!highlightNodes.size) return n.color;
    if (n.id === selectedId) return '#ffffff';
    return highlightNodes.has(n.id) ? n.color : '#23233a';
  })
  .nodeVal(n => Math.pow(Math.max(n.size, 4) / 4, 3))
  .nodeOpacity(0.92)
  .nodeResolution(10)
  .nodeVisibility(n => !hiddenCommunities.has(n.community))
  .linkVisibility(l => {
    const a = nodeById.get(l._s), b = nodeById.get(l._t);
    return !hiddenCommunities.has(a.community) && !hiddenCommunities.has(b.community);
  })
  .linkColor(l => highlightLinks.has(l) ? '#ffffff' : '#8888aa')
  .linkOpacity(0.22)
  .linkWidth(l => highlightLinks.has(l) ? 1.2 : 0)
  .linkLabel(l => esc(l.title))
  .linkDirectionalArrowLength(l => highlightLinks.has(l) ? 4 : 0)
  .linkDirectionalArrowRelPos(1)
  .onNodeClick(n => selectNode(n.id, true))
  .onBackgroundClick(clearSelection)
  .graphData({ nodes: NODES, links: LINKS });

// the library sizes its canvas to the window before flex layout settles; re-measure once
requestAnimationFrame(() => Graph.width(graphEl.clientWidth).height(graphEl.clientHeight));
window.addEventListener('resize', () => {
  Graph.width(graphEl.clientWidth).height(graphEl.clientHeight);
});

function refreshHighlight() {
  Graph.nodeColor(Graph.nodeColor());
  Graph.linkColor(Graph.linkColor());
  Graph.linkWidth(Graph.linkWidth());
  Graph.linkDirectionalArrowLength(Graph.linkDirectionalArrowLength());
}

function refreshVisibility() {
  Graph.nodeVisibility(Graph.nodeVisibility());
  Graph.linkVisibility(Graph.linkVisibility());
}

function selectNode(id, fly) {
  const n = nodeById.get(id);
  if (!n) return;
  selectedId = id;
  highlightNodes.clear();
  highlightLinks.clear();
  highlightNodes.add(id);
  (adjacency.get(id) || []).forEach(e => {
    highlightNodes.add(e.otherId);
    highlightLinks.add(e.link);
  });
  refreshHighlight();
  showInfo(n);
  if (fly) flyTo(n);
}

function clearSelection() {
  selectedId = null;
  highlightNodes.clear();
  highlightLinks.clear();
  refreshHighlight();
  document.getElementById('info-content').innerHTML = '<span class="empty">Click a node to inspect it</span>';
}

function flyTo(n) {
  if (n.x === undefined) return;
  const dist = 260;
  const r = Math.hypot(n.x, n.y, n.z) || 1;
  const ratio = 1 + dist / r;
  Graph.cameraPosition({ x: n.x * ratio, y: n.y * ratio, z: n.z * ratio }, n, 900);
}

function showInfo(n) {
  const neighbors = adjacency.get(n.id) || [];
  const items = neighbors.slice(0, 60).map(e => {
    const other = nodeById.get(e.otherId);
    if (!other) return '';
    const rel = e.out ? (esc(e.relation) + ' &rarr;') : ('&larr; ' + esc(e.relation));
    return '<span class="neighbor-link" style="border-left-color:' + esc(other.color) + '" ' +
           'onclick="selectNode(\'' + e.otherId.replace(/\\/g,'\\\\').replace(/'/g,"\\'") + '\', true)">' +
           '<span style="color:#778">' + rel + '</span> ' + esc(other.label) + '</span>';
  }).join('');
  const more = neighbors.length > 60 ? '<div class="empty">&hellip; ' + (neighbors.length - 60) + ' more</div>' : '';
  document.getElementById('info-content').innerHTML =
    '<div class="field"><b>' + esc(n.label) + '</b></div>' +
    '<div class="field"><span class="legend-dot" style="display:inline-block;vertical-align:-2px;background:' + esc(communityColor.get(n.community) || n.color) + '"></span> ' + esc(n.community_name) + '</div>' +
    (n.source_file ? '<div class="field">File: <b>' + esc(n.source_file) + '</b></div>' : '') +
    (n.file_type ? '<div class="field">Type: <b>' + esc(n.file_type) + '</b></div>' : '') +
    '<div class="field">Degree: <b>' + n.degree + '</b></div>' +
    (items ? '<div class="field" style="margin-top:8px">Neighbors (' + neighbors.length + '):</div><div id="neighbors-list">' + items + more + '</div>' : '');
}

// --- Search ---
const searchInput = document.getElementById('search');
const searchResults = document.getElementById('search-results');
searchInput.addEventListener('input', () => {
  const q = searchInput.value.trim().toLowerCase();
  if (q.length < 2) { searchResults.style.display = 'none'; searchResults.innerHTML = ''; return; }
  const hits = NODES.filter(n =>
    n.label.toLowerCase().includes(q) || n.source_file.toLowerCase().includes(q)
  ).slice(0, 30);
  searchResults.innerHTML = hits.map(n =>
    '<div class="search-item" onclick="pickSearch(\'' + n.id.replace(/\\/g,'\\\\').replace(/'/g,"\\'") + '\')">' +
    '<span class="legend-dot" style="display:inline-block;width:8px;height:8px;vertical-align:0;background:' + esc(n.color) + '"></span> ' +
    esc(n.label) + ' <span style="color:#667">' + esc(n.source_file) + '</span></div>'
  ).join('') || '<div class="empty" style="font-size:12px;color:#555">No matches</div>';
  searchResults.style.display = 'block';
});
function pickSearch(id) {
  searchResults.style.display = 'none';
  selectNode(id, true);
}

// --- Legend ---
const legendEl = document.getElementById('legend');
legendEl.innerHTML = LEGEND.map(l =>
  '<div class="legend-item" id="legend-' + l.cid + '" onclick="toggleCommunity(' + l.cid + ')">' +
  '<input type="checkbox" class="legend-cb" checked onclick="event.stopPropagation();toggleCommunity(' + l.cid + ')">' +
  '<span class="legend-dot" style="background:' + esc(l.color) + '"></span>' +
  '<span class="legend-label">' + l.label + '</span>' +
  '<span class="legend-count">' + l.count + '</span></div>'
).join('');

function toggleCommunity(cid) {
  const item = document.getElementById('legend-' + cid);
  const cb = item.querySelector('.legend-cb');
  if (hiddenCommunities.has(cid)) {
    hiddenCommunities.delete(cid);
    item.classList.remove('dimmed');
    cb.checked = true;
  } else {
    hiddenCommunities.add(cid);
    item.classList.add('dimmed');
    cb.checked = false;
  }
  updateSelectAll();
  refreshVisibility();
}

function toggleAllCommunities(hide) {
  hiddenCommunities.clear();
  if (hide) LEGEND.forEach(l => hiddenCommunities.add(l.cid));
  LEGEND.forEach(l => {
    const item = document.getElementById('legend-' + l.cid);
    item.classList.toggle('dimmed', hide);
    item.querySelector('.legend-cb').checked = !hide;
  });
  updateSelectAll();
  refreshVisibility();
}

function updateSelectAll() {
  const cb = document.getElementById('select-all-cb');
  if (hiddenCommunities.size === 0) { cb.checked = true; cb.indeterminate = false; }
  else if (hiddenCommunities.size === LEGEND.length) { cb.checked = false; cb.indeterminate = false; }
  else { cb.checked = false; cb.indeterminate = true; }
}

// --- Camera controls ---
let rotateTimer = null;
function toggleAutoRotate() {
  const btn = document.getElementById('rotate-btn');
  if (rotateTimer) {
    clearInterval(rotateTimer);
    rotateTimer = null;
    btn.classList.remove('active');
    return;
  }
  btn.classList.add('active');
  rotateTimer = setInterval(() => {
    const cam = Graph.cameraPosition();
    const r = Math.hypot(cam.x, cam.z);
    const angle = Math.atan2(cam.x, cam.z) + 0.004;
    Graph.cameraPosition({ x: r * Math.sin(angle), y: cam.y, z: r * Math.cos(angle) });
  }, 30);
}

function resetView() {
  if (rotateTimer) toggleAutoRotate();
  clearSelection();
  Graph.zoomToFit(900, 40);
}

// stop auto-rotate as soon as the user grabs the graph
let userInteracted = false;
graphEl.addEventListener('pointerdown', () => {
  userInteracted = true;
  if (rotateTimer) toggleAutoRotate();
});

// frame the whole graph: once early, once when the layout settles (unless the user took over)
setTimeout(() => { if (!userInteracted) Graph.zoomToFit(1200, 40); }, 2500);
let framedOnce = false;
Graph.onEngineStop(() => {
  if (!framedOnce && !userInteracted) Graph.zoomToFit(1000, 40);
  framedOnce = true;
});
</script>
</body>
</html>
"""

out = (
    TEMPLATE
    .replace("__NODES__", js(nodes))
    .replace("__LINKS__", js(links))
    .replace("__LEGEND__", js(legend))
    .replace("__STATS__", stats)
)
open(DST, "w", encoding="utf-8").write(out)
print("wrote", DST, len(out), "bytes")

# Re-inject the "3D view" button into graph.html if a fresh graphify run removed it
if 'id="view3d-btn"' not in src:
    BTN_CSS = (
        '  #view3d-btn { position: fixed; top: 12px; left: 12px; z-index: 10; background: #1a1a2eE6; '
        'border: 1px solid #3a3a5e; color: #ccc; padding: 6px 12px; border-radius: 6px; font-size: 12px; '
        'text-decoration: none; }\n'
        '  #view3d-btn:hover { border-color: #4E79A7; color: #fff; }\n'
    )
    patched = src.replace("</style>", BTN_CSS + "</style>", 1).replace(
        '<div id="graph"></div>',
        '<div id="graph"></div>\n<a id="view3d-btn" href="graph3d.html" title="Open rotatable 3D view">3D view</a>',
        1,
    )
    open(SRC, "w", encoding="utf-8").write(patched)
    print("re-added 3D view button to graph.html")

const fs = require('fs');
const path = require('path');

const root = process.argv[2];
const ua = path.join(root, '.ua');
const assembled = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'assembled-graph.json'), 'utf8'));
const layers = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'layers.json'), 'utf8'));
const tour = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'tour.json'), 'utf8'));
const commit = require('child_process').execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
const graph = {
  version: '1.0.0',
  project: {
    name: 'tick-stock-panel',
    languages: ['batch','config','css','csv','dockerfile','docx','example','feather','html','icns','in','ipynb','isl','iss','javascript','json','jsonl','makefile','markdown','powershell','python','ruby','rust','shell','sig','snap','spec','toml','txt','typed','typescript','unknown','webmanifest','yaml'],
    frameworks: ['Docker'],
    description: 'TSP 是一个自托管的 A 股智能量化工作台，提供多数据源能力路由、选股、监控、分析与回测功能。',
    analyzedAt: new Date().toISOString(),
    gitCommitHash: commit,
  },
  nodes: assembled.nodes,
  edges: assembled.edges,
  layers,
  tour,
};
const issues = [];
const warnings = [];
const validTypes = new Set(['file','function','class','config','document','service','table','endpoint','pipeline','schema','resource']);
const nodeIds = new Set();
for (const [i, n] of graph.nodes.entries()) {
  if (!n.id) issues.push(`Node[${i}] missing id`);
  else if (nodeIds.has(n.id)) issues.push(`Duplicate node ID '${n.id}'`);
  else nodeIds.add(n.id);
  if (!validTypes.has(n.type)) issues.push(`Node '${n.id}' invalid type '${n.type}'`);
  if (!n.name) issues.push(`Node '${n.id}' missing name`);
  if (!n.summary) issues.push(`Node '${n.id}' missing summary`);
  if (!Array.isArray(n.tags) || n.tags.length === 0) issues.push(`Node '${n.id}' missing tags`);
}
for (const [i, e] of graph.edges.entries()) {
  if (!nodeIds.has(e.source)) issues.push(`Edge[${i}] missing source '${e.source}'`);
  if (!nodeIds.has(e.target)) issues.push(`Edge[${i}] missing target '${e.target}'`);
}
const fileLevel = new Set(['file','config','document','service','pipeline','table','schema','resource','endpoint']);
const fileNodes = graph.nodes.filter(n => fileLevel.has(n.type)).map(n => n.id);
const assigned = new Map();
if (!Array.isArray(graph.layers) || graph.layers.length < 3 || graph.layers.length > 10) issues.push('Layers must contain 3-10 entries');
for (const layer of graph.layers) {
  if (!layer.id || !layer.name || !layer.description || !Array.isArray(layer.nodeIds) || !layer.nodeIds.length) issues.push(`Invalid layer '${layer.id || '<missing>'}'`);
  for (const id of layer.nodeIds || []) {
    if (!nodeIds.has(id)) issues.push(`Layer '${layer.id}' references missing node '${id}'`);
    if (assigned.has(id)) issues.push(`Node '${id}' is assigned to multiple layers`);
    assigned.set(id, layer.id);
  }
}
for (const id of fileNodes) if (!assigned.has(id)) issues.push(`File node '${id}' is unassigned`);
if (!Array.isArray(graph.tour) || graph.tour.length < 5 || graph.tour.length > 15) issues.push('Tour must contain 5-15 entries');
for (const [i, step] of graph.tour.entries()) {
  if (step.order !== i + 1 || !step.title || !step.description || !Array.isArray(step.nodeIds) || !step.nodeIds.length) issues.push(`Invalid tour step ${i + 1}`);
  for (const id of step.nodeIds || []) if (!nodeIds.has(id)) issues.push(`Tour step ${i + 1} references missing node '${id}'`);
}
for (const n of graph.nodes) if (!graph.edges.some(e => e.source === n.id || e.target === n.id)) warnings.push(`Orphan node '${n.id}'`);
fs.writeFileSync(path.join(ua, 'intermediate', 'assembled-graph.json'), JSON.stringify(graph, null, 2));
fs.writeFileSync(path.join(ua, 'intermediate', 'review.json'), JSON.stringify({ issues, warnings, stats: {
  totalNodes: graph.nodes.length, totalEdges: graph.edges.length, totalLayers: graph.layers.length, tourSteps: graph.tour.length,
  nodeTypes: graph.nodes.reduce((a,n) => ((a[n.type] = (a[n.type] || 0) + 1), a), {}),
  edgeTypes: graph.edges.reduce((a,e) => ((a[e.type] = (a[e.type] || 0) + 1), a), {}),
}}, null, 2));
console.log(JSON.stringify({ issues: issues.length, warnings: warnings.length, nodes: graph.nodes.length, edges: graph.edges.length, layers: graph.layers.length, tour: graph.tour.length }));
process.exit(issues.length ? 2 : 0);

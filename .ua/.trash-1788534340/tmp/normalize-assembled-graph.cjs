const fs = require('fs');
const graphPath = process.argv[2];
const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));
const fileTypes = new Set(['file','config','document','service','pipeline','table','schema','resource','endpoint']);
const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
const fileNodes = nodes.filter(n => fileTypes.has(n.type));
const normalizeTag = value => String(value).trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
for (const node of nodes) {
  const tags = Array.isArray(node.tags) ? node.tags.map(normalizeTag).filter(Boolean) : [];
  node.tags = [...new Set(tags.length ? tags : ['untagged'])];
}
const groups = [
  ['layer:documentation', 'Documentation', 'Project guides, operational references, and user-facing documentation.', n => n.type === 'document'],
  ['layer:configuration-infrastructure', 'Configuration and Infrastructure', 'Runtime configuration, build and deployment definitions, and infrastructure resources.', n => ['config','service','pipeline','schema','resource','table','endpoint'].includes(n.type)],
  ['layer:backend', 'Backend Application', 'FastAPI application, data services, strategies, and backend test coverage.', n => /^backend\//.test(n.filePath || '')],
  ['layer:frontend', 'Frontend Application', 'React client, frontend configuration, and extension surfaces.', n => /^frontend\//.test(n.filePath || '')],
  ['layer:project-tooling', 'Project Tooling and Packaging', 'Repository-level scripts, packaging assets, and remaining project support files.', () => true],
];
const assigned = new Set();
graph.layers = groups.map(([id, name, description, predicate]) => {
  const nodeIds = fileNodes.filter(n => !assigned.has(n.id) && predicate(n)).map(n => { assigned.add(n.id); return n.id; });
  return { id, name, description, nodeIds };
}).filter(layer => layer.nodeIds.length);
const byPath = new Map(fileNodes.map(n => [n.filePath, n.id]));
const pick = (...paths) => paths.map(p => byPath.get(p)).find(Boolean);
const first = predicate => (fileNodes.find(predicate) || {}).id;
const tourCandidates = [
  ['Project Overview', 'Start with the project documentation to understand scope and operational conventions.', pick('README.md') || first(n => n.type === 'document')],
  ['Backend Entry Point', 'Follow the FastAPI application lifecycle and route registration from the backend entry point.', pick('backend/app/main.py') || first(n => /^backend\/app\//.test(n.filePath || ''))],
  ['API Surface', 'Review the API layer that exposes application capabilities to clients.', pick('backend/app/api/routes.py') || first(n => /^backend\/app\/api\//.test(n.filePath || ''))],
  ['Service and Domain Logic', 'Trace backend services and domain logic after the API boundary.', first(n => /^backend\/app\/services\//.test(n.filePath || '')) || first(n => /^backend\/app\/strategy\//.test(n.filePath || ''))],
  ['Frontend Application', 'Finish with the React client entry point and its route composition.', pick('frontend/src/main.tsx') || pick('frontend/src/router.tsx') || first(n => /^frontend\/src\//.test(n.filePath || ''))],
];
graph.tour = tourCandidates.filter(([, , id]) => id).map(([title, description, id], index) => ({order:index + 1, title, description, nodeIds:[id]}));
fs.writeFileSync(graphPath, JSON.stringify(graph, null, 2) + '\n');

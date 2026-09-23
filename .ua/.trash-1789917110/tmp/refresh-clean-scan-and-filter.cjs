const fs = require('fs');
const path = require('path');

const root = process.argv[2];
const ua = path.join(root, '.ua');
const oldScanPath = path.join(ua, 'intermediate', 'scan-result.json');
const freshScan = JSON.parse(fs.readFileSync(path.join(ua, 'tmp', 'ua-clean-scan.json'), 'utf8'));
const freshImports = JSON.parse(fs.readFileSync(path.join(ua, 'tmp', 'ua-clean-imports.json'), 'utf8'));
const oldScan = JSON.parse(fs.readFileSync(oldScanPath, 'utf8'));
const scan = {
  name: oldScan.name,
  description: oldScan.description,
  languages: oldScan.languages,
  frameworks: oldScan.frameworks,
  files: freshScan.files,
  totalFiles: freshScan.totalFiles,
  filteredByIgnore: freshScan.filteredByIgnore,
  estimatedComplexity: freshScan.estimatedComplexity,
  importMap: freshImports.importMap,
};
fs.writeFileSync(oldScanPath, JSON.stringify(scan, null, 2));

const graphPath = path.join(ua, 'intermediate', 'assembled-graph.json');
const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));
const removed = new Set(graph.nodes.filter(n => (n.filePath || '').startsWith('.ua/')).map(n => n.id));
graph.nodes = graph.nodes.filter(n => !removed.has(n.id));
graph.edges = graph.edges.filter(e => !removed.has(e.source) && !removed.has(e.target));
const isGraphArtifact = id => removed.has(id) || id.includes(':.ua/');
graph.layers = graph.layers.map(l => ({ ...l, nodeIds: l.nodeIds.filter(id => !isGraphArtifact(id)) })).filter(l => l.nodeIds.length);
graph.tour = graph.tour.map(step => ({ ...step, nodeIds: step.nodeIds.filter(id => !isGraphArtifact(id)) })).filter(step => step.nodeIds.length).map((step, i) => ({ ...step, order: i + 1 }));
fs.writeFileSync(graphPath, JSON.stringify(graph, null, 2));
fs.writeFileSync(path.join(ua, 'intermediate', 'layers.json'), JSON.stringify(graph.layers, null, 2));
fs.writeFileSync(path.join(ua, 'intermediate', 'tour.json'), JSON.stringify(graph.tour, null, 2));
console.log(JSON.stringify({ removedNodes: removed.size, remainingNodes: graph.nodes.length, remainingEdges: graph.edges.length, files: scan.totalFiles, imports: Object.values(scan.importMap).reduce((n, targets) => n + targets.length, 0) }));

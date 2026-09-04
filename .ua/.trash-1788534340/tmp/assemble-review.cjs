const fs = require('fs');
const path = require('path');

const [graphPath, scanPath, batchesGlobDir, outputPath] = process.argv.slice(2);
const validTypes = new Set(['file','function','class','module','concept','config','document','service','table','endpoint','pipeline','schema','resource','domain','flow','step']);
const validEdgeTypes = new Set(['imports','exports','contains','inherits','implements','calls','subscribes','publishes','middleware','reads_from','writes_to','transforms','validates','depends_on','tested_by','configures','related','similar_to','deploys','serves','migrates','documents','provisions','routes','defines_schema','triggers','contains_flow','flow_step','cross_domain']);
const fileTypes = new Set(['file','config','document','service','pipeline','table','schema','resource','endpoint']);
const prefixFor = type => `${type}:`;
function addUnique(list, text) { if (!list.includes(text)) list.push(text); }
function main() {
  const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));
  const scan = JSON.parse(fs.readFileSync(scanPath, 'utf8'));
  const issues = [], warnings = [];
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph.edges) ? graph.edges : [];
  if (!Array.isArray(graph.nodes)) issues.push('graph.nodes is missing or not an array');
  if (!Array.isArray(graph.edges)) issues.push('graph.edges is missing or not an array');
  const byId = new Map(), duplicateIds = new Map();
  nodes.forEach((node, index) => {
    if (!node || typeof node !== 'object') { issues.push(`Node[${index}] is not an object`); return; }
    for (const field of ['id','type','name','summary','complexity']) if (typeof node[field] !== 'string' || !node[field].trim()) issues.push(`Node[${index}] missing or invalid ${field}`);
    if (typeof node.id === 'string' && node.id && byId.has(node.id)) { const indices = duplicateIds.get(node.id) || [byId.get(node.id).__index]; indices.push(index); duplicateIds.set(node.id, indices); }
    if (typeof node.id === 'string') byId.set(node.id, {...node, __index:index});
    if (!validTypes.has(node.type)) issues.push(`Node[${index}] '${node.id || '<missing>'}' has invalid type '${node.type}'`);
    if (typeof node.id === 'string' && validTypes.has(node.type) && !node.id.startsWith(prefixFor(node.type))) warnings.push(`Node '${node.id}' type '${node.type}' does not match its ID prefix`);
    if (!Array.isArray(node.tags) || !node.tags.length || node.tags.some(t => typeof t !== 'string' || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(t))) issues.push(`Node[${index}] '${node.id || '<missing>'}' has invalid tags`);
    if (typeof node.summary === 'string' && typeof node.name === 'string' && node.summary.trim().toLowerCase() === node.name.trim().toLowerCase()) warnings.push(`Node '${node.id}' summary merely repeats its name`);
  });
  for (const [id, indices] of duplicateIds) issues.push(`Duplicate node ID '${id}' at indices ${indices.join(', ')}`);
  if (!nodes.length) issues.push('Graph has zero nodes');
  if (!edges.length) issues.push('Graph has zero edges');
  const edgeKeys = new Set();
  edges.forEach((edge, index) => {
    if (!edge || typeof edge !== 'object') { issues.push(`Edge[${index}] is not an object`); return; }
    for (const field of ['source','target','type','direction']) if (typeof edge[field] !== 'string' || !edge[field].trim()) issues.push(`Edge[${index}] missing or invalid ${field}`);
    if (!byId.has(edge.source)) issues.push(`Edge[${index}] source '${edge.source}' not found`);
    if (!byId.has(edge.target)) issues.push(`Edge[${index}] target '${edge.target}' not found`);
    if (!validEdgeTypes.has(edge.type)) issues.push(`Edge[${index}] has invalid type '${edge.type}'`);
    if (!['forward','backward','bidirectional'].includes(edge.direction)) issues.push(`Edge[${index}] has invalid direction '${edge.direction}'`);
    if (typeof edge.weight !== 'number' || edge.weight < 0 || edge.weight > 1) issues.push(`Edge[${index}] has invalid weight '${edge.weight}'`);
    if (edge.source === edge.target) warnings.push(`Edge[${index}] is self-referencing ('${edge.source}')`);
    edgeKeys.add(`${edge.source}\u0000${edge.target}\u0000${edge.type}`);
  });
  const layers = Array.isArray(graph.layers) ? graph.layers : [];
  const tour = Array.isArray(graph.tour) ? graph.tour : [];
  if (!layers.length) issues.push('Graph has zero layers');
  if (!tour.length) issues.push('Graph has zero tour steps');
  const assigned = new Map();
  layers.forEach((layer, i) => {
    if (!layer || typeof layer !== 'object') { issues.push(`Layer[${i}] is not an object`); return; }
    if (!Array.isArray(layer.nodeIds)) { issues.push(`Layer '${layer.id || i}' nodeIds is missing or not an array`); return; }
    if (!layer.nodeIds.length) warnings.push(`Layer '${layer.id || i}' has no nodeIds`);
    layer.nodeIds.forEach(id => { if (!byId.has(id)) issues.push(`Layer '${layer.id || i}' references missing node '${id}'`); else { const a = assigned.get(id) || []; a.push(layer.id || String(i)); assigned.set(id,a); } });
  });
  nodes.filter(n => fileTypes.has(n.type)).forEach(n => { const a=assigned.get(n.id)||[]; if (!a.length) issues.push(`File-level node '${n.id}' is not in any layer`); if (a.length > 1) issues.push(`File-level node '${n.id}' appears in multiple layers: ${a.join(', ')}`); });
  tour.forEach((step, i) => { if (!Array.isArray(step.nodeIds) || !step.nodeIds.length) warnings.push(`Tour step[${i}] has no nodeIds`); else step.nodeIds.forEach(id=>{if(!byId.has(id)) issues.push(`Tour step[${i}] references missing node '${id}'`);}); });
  const orders=tour.map(s=>s.order); if (orders.some((o,i)=>o!==i+1) || new Set(orders).size!==orders.length) warnings.push('Tour orders are not sequential starting from 1');
  if (tour.length < 5 || tour.length > 15) warnings.push(`Tour has ${tour.length} steps; expected 5-15`);
  const connected = new Set(edges.flatMap(e=>[e.source,e.target])); const orphans=nodes.filter(n=>!connected.has(n.id)); if(orphans.length) warnings.push(`${orphans.length} nodes have no edges (orphan)`);
  const inventory = Array.isArray(scan.files) ? scan.files.map(f => typeof f === 'string' ? f : f.path).filter(Boolean) : [];
  const inventorySet = new Set(inventory);
  const pathNode = new Map(); nodes.filter(n=>fileTypes.has(n.type) && typeof n.filePath === 'string').forEach(n=>pathNode.set(n.filePath.replace(/\\/g,'/'),n));
  const missingInventory=inventory.filter(p=>!pathNode.has(p.replace(/\\/g,'/'))); if(missingInventory.length) issues.push(`${missingInventory.length} scan inventory files have no graph file-level node: ${missingInventory.slice(0,20).join(', ')}${missingInventory.length>20?' ...':''}`);
  const extraNodes=[...pathNode.keys()].filter(p=>!inventorySet.has(p)); if(extraNodes.length) issues.push(`${extraNodes.length} graph file-level node paths are absent from scan inventory: ${extraNodes.slice(0,20).join(', ')}${extraNodes.length>20?' ...':''}`);
  const importMap = scan.importMap && typeof scan.importMap === 'object' ? scan.importMap : {};
  let expectedImports=0, missingImports=0;
  for (const [sourcePath, targets] of Object.entries(importMap)) {
    if (!Array.isArray(targets)) continue;
    const source=pathNode.get(sourcePath); if(!source) continue;
    for (const targetPath of targets) { const target=pathNode.get(String(targetPath).replace(/\\/g,'/')); if(!target) continue; expectedImports++; if(!edgeKeys.has(`${source.id}\u0000${target.id}\u0000imports`)) missingImports++; }
  }
  if (missingImports) issues.push(`${missingImports} of ${expectedImports} resolvable imports in scan-result importMap have no matching imports edge`);
  const batchFiles=fs.readdirSync(batchesGlobDir).filter(n=>/^batch-.*\.json$/.test(n)); let emptyParts=0, batchNodes=0, batchEdges=0, missingBatchNodes=0, missingBatchEdges=0;
  for (const file of batchFiles) { const batch=JSON.parse(fs.readFileSync(path.join(batchesGlobDir,file),'utf8')); const bn=Array.isArray(batch.nodes)?batch.nodes:[]; const be=Array.isArray(batch.edges)?batch.edges:[]; if(!bn.length&&!be.length) emptyParts++; batchNodes+=bn.length; batchEdges+=be.length; for(const n of bn) if(!byId.has(n.id)) missingBatchNodes++; for(const e of be) if(!edgeKeys.has(`${e.source}\u0000${e.target}\u0000${e.type}`)) missingBatchEdges++; }
  if(emptyParts) warnings.push(`${emptyParts} batch parts are empty`); if(missingBatchNodes) issues.push(`${missingBatchNodes} batch nodes are absent from assembled graph`); if(missingBatchEdges) issues.push(`${missingBatchEdges} batch edges are absent from assembled graph`);
  const countBy=(items,key)=>items.reduce((a,x)=>{a[x[key]]=(a[x[key]]||0)+1;return a;},{});
  const result={approved:issues.length===0,issues,warnings,stats:{totalNodes:nodes.length,totalEdges:edges.length,totalLayers:layers.length,tourSteps:tour.length,nodeTypes:countBy(nodes,'type'),edgeTypes:countBy(edges,'type'),scanFiles:inventory.length,expectedResolvableImports:expectedImports,missingImportEdges:missingImports,batchFiles:batchFiles.length,batchNodes,batchEdges,emptyBatchParts:emptyParts}};
  fs.writeFileSync(outputPath, JSON.stringify(result,null,2));
}
try { main(); } catch (err) { console.error(err.stack || err.message); process.exit(1); }

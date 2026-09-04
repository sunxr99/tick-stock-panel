const fs = require('fs');

function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) throw new Error('Usage: node ua-tour-analyze.js <input> <output>');
  const graph = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph.edges) ? graph.edges : [];
  const byId = new Map(nodes.map(node => [node.id, node]));
  const fanIn = new Map(nodes.map(node => [node.id, 0]));
  const fanOut = new Map(nodes.map(node => [node.id, 0]));
  const forward = new Map(nodes.map(node => [node.id, []]));
  for (const edge of edges) {
    if (byId.has(edge.source) && byId.has(edge.target)) {
      fanOut.set(edge.source, fanOut.get(edge.source) + 1);
      fanIn.set(edge.target, fanIn.get(edge.target) + 1);
      if (edge.type === 'imports' || edge.type === 'calls') forward.get(edge.source).push(edge.target);
    }
  }
  const ranked = (metric, label) => [...nodes].sort((a,b) => metric.get(b.id)-metric.get(a.id) || a.id.localeCompare(b.id)).slice(0,20).map(node => ({id:node.id,[label]:metric.get(node.id),name:node.name}));
  const counts = [...fanIn.values()].sort((a,b)=>a-b);
  const lowCutoff = counts[Math.floor(counts.length * .25)] || 0;
  const outCutoff = counts[Math.max(0, Math.floor(counts.length * .9))] || 0;
  const entryNames = /^(index\.(ts|js)|main\.(ts|js|py|rs)|app\.(ts|js|py)|server\.(ts|js)|mod\.rs|main\.go|manage\.py|wsgi\.py|asgi\.py|run\.py|__main__\.py|Application\.java|Main\.java|Program\.cs|config\.ru|index\.php|App\.swift|Application\.kt|main\.(cpp|c))$/;
  const candidates = nodes.map(node => {
    const path = node.filePath || '';
    const depth = path ? path.split('/').length : 99;
    let score = 0;
    if (node.type === 'document' && path === 'README.md') score += 5;
    else if (node.type === 'document' && depth === 1 && /\.md$/i.test(path)) score += 2;
    if (node.type === 'file') {
      if (entryNames.test(node.name || '')) score += 3;
      if (depth <= 2) score += 1;
      if (fanOut.get(node.id) >= outCutoff) score += 1;
      if (fanIn.get(node.id) <= lowCutoff) score += 1;
    }
    return {id:node.id,score,name:node.name,summary:node.summary};
  }).filter(item => item.score > 0).sort((a,b)=>b.score-a.score || a.id.localeCompare(b.id)).slice(0,5);
  const start = candidates.find(c => byId.get(c.id)?.type === 'file');
  const depthMap = {}, order = [], byDepth = {};
  if (start) {
    const queue = [start.id]; depthMap[start.id] = 0;
    for (let i=0; i<queue.length; i++) {
      const id = queue[i], depth = depthMap[id]; order.push(id);
      (byDepth[depth] ||= []).push(id);
      for (const target of forward.get(id) || []) if (!(target in depthMap)) { depthMap[target] = depth + 1; queue.push(target); }
    }
  }
  const categories = {documentation:[], infrastructure:[], data:[], config:[]};
  for (const n of nodes) {
    const item={id:n.id,name:n.name,type:n.type,summary:n.summary};
    if(n.type==='document') categories.documentation.push(item);
    else if(['service','pipeline','resource'].includes(n.type)) categories.infrastructure.push(item);
    else if(['table','schema','endpoint'].includes(n.type)) categories.data.push(item);
    else if(n.type==='config') categories.config.push(item);
  }
  const results={scriptCompleted:true,entryPointCandidates:candidates,fanInRanking:ranked(fanIn,'fanIn'),fanOutRanking:ranked(fanOut,'fanOut'),bfsTraversal:{startNode:start?.id || null,order,depthMap,byDepth},nonCodeFiles:categories,clusters:[],layers:{count:(graph.layers||[]).length,list:graph.layers||[]},nodeSummaryIndex:Object.fromEntries(nodes.map(n=>[n.id,{name:n.name,type:n.type,summary:n.summary}])),totalNodes:nodes.length,totalEdges:edges.length};
  fs.writeFileSync(outputPath, JSON.stringify(results,null,2));
}
try { main(); } catch (error) { console.error(error.stack || error.message); process.exit(1); }

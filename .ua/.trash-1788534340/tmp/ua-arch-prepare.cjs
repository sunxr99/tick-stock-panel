const fs = require('fs');
const graph = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const fileTypes = new Set(['file', 'config', 'document', 'service', 'pipeline', 'table', 'schema', 'resource', 'endpoint']);
const fileNodes = graph.nodes.filter((node) => fileTypes.has(node.type));
const ids = new Set(fileNodes.map((node) => node.id));
const allEdges = graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
const importEdges = allEdges.filter((edge) => edge.type === 'imports');
fs.writeFileSync(process.argv[3], JSON.stringify({ fileNodes, importEdges, allEdges }, null, 2));

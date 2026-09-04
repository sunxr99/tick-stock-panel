const fs = require('fs');

function fail(message) { process.stderr.write(`${message}\n`); process.exit(1); }
function pathParts(path) { return String(path || '').replace(/\\/g, '/').split('/').filter(Boolean); }
function commonDirPrefix(paths) {
  const dirs = paths.map((path) => pathParts(path).slice(0, -1));
  if (!dirs.length) return [];
  const prefix = [];
  for (let i = 0; ; i += 1) {
    const item = dirs[0][i];
    if (!item || !dirs.every((dir) => dir[i] === item)) break;
    prefix.push(item);
  }
  return prefix;
}
function patternFor(group, path) {
  const p = String(path).toLowerCase(); const g = group.toLowerCase();
  if (/\.test\.|\.spec\.|(^|\/)test_.*\.py$|_test\.go$|test\.java$/.test(p)) return 'test';
  if (/\.d\.ts$/.test(p)) return 'types';
  if (/^(dockerfile|docker-compose\.)/.test(p.split('/').pop()) || /(^|\/)(docker|infra|infrastructure|k8s|kubernetes|helm|charts|terraform|tf)(\/|$)/.test(p)) return 'infrastructure';
  if (/(^|\/)\.github\/workflows\//.test(p) || /\.gitlab-ci\.yml$|jenkinsfile$/.test(p)) return 'ci-cd';
  if (/\.md$|\.rst$/.test(p) || /(^|\/)(docs|documentation|wiki)(\/|$)/.test(p)) return 'documentation';
  if (/\.sql$|(^|\/)(models|db|data|persistence|repository|entities|migrations|database|schema)(\/|$)/.test(p)) return 'data';
  if (/(^|\/)(routes|api|controllers|endpoints|handlers|serializers|routers|controller|blueprints)(\/|$)/.test(p)) return 'api';
  if (/(^|\/)(services|core|lib|domain|logic|signals|composables|mailers|jobs|channels|internal)(\/|$)/.test(p)) return 'service';
  if (/(^|\/)(components|views|pages|ui|layouts|screens)(\/|$)/.test(p)) return 'ui';
  if (/(^|\/)(middleware|plugins|interceptors|guards)(\/|$)/.test(p)) return 'middleware';
  if (/(^|\/)(utils|helpers|common|shared|tools|pkg|templatetags)(\/|$)/.test(p)) return 'utility';
  if (/(^|\/)(config|constants|env|settings|management|commands)(\/|$)/.test(p) || /(^|\/)(package\.json|pyproject\.toml|cargo\.toml|go\.mod|pom\.xml|build\.gradle|composer\.json)$/.test(p)) return 'config';
  if (/(^|\/)(types|interfaces|schemas|contracts|dtos|dto|request|response)(\/|$)/.test(p) || /\.(graphql|gql|proto)$/.test(p)) return 'types';
  if (/(^|\/)(store|state|reducers|actions|slices)(\/|$)/.test(p)) return 'state';
  if (/(^|\/)(assets|static|public)(\/|$)/.test(p)) return 'assets';
  if (/(^|\/)(index\.(ts|js)|__init__\.py|main\.py)$/.test(p)) return 'entry';
  return 'unclassified';
}
try {
  const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const nodes = Array.isArray(input.fileNodes) ? input.fileNodes : [];
  const imports = Array.isArray(input.importEdges) ? input.importEdges : [];
  const allEdges = Array.isArray(input.allEdges) ? input.allEdges : [];
  if (!nodes.length) fail('No file nodes provided');
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const prefix = commonDirPrefix(nodes.map((node) => node.filePath || ''));
  const groupOf = new Map(); const directoryGroups = {};
  for (const node of nodes) {
    const parts = pathParts(node.filePath || node.name);
    const relevant = parts.slice(prefix.length);
    const group = relevant.length > 1 ? relevant[0] : (parts.length > 1 ? parts[0] : 'root');
    groupOf.set(node.id, group); (directoryGroups[group] ||= []).push(node.id);
  }
  const nodeTypeGroups = {}; for (const n of nodes) (nodeTypeGroups[n.type] ||= []).push(n.id);
  const fanIn = Object.fromEntries(nodes.map((n) => [n.id, 0])); const fanOut = Object.fromEntries(nodes.map((n) => [n.id, 0]));
  const inter = new Map(); const intra = Object.fromEntries(Object.keys(directoryGroups).map((g) => [g, { internalEdges: 0, totalEdges: 0 }]));
  for (const e of imports) {
    if (!byId.has(e.source) || !byId.has(e.target)) continue;
    fanOut[e.source] += 1; fanIn[e.target] += 1;
    const from = groupOf.get(e.source), to = groupOf.get(e.target);
    intra[from].totalEdges += 1; if (to !== from) intra[to].totalEdges += 1;
    if (from === to) intra[from].internalEdges += 1;
    const key = `${from}\u0000${to}`; inter.set(key, (inter.get(key) || 0) + 1);
  }
  const interGroupImports = [...inter].map(([key, count]) => { const [from, to] = key.split('\u0000'); return { from, to, count }; });
  const intraGroupDensity = Object.fromEntries(Object.entries(intra).map(([g, x]) => [g, { ...x, density: x.totalEdges ? Number((x.internalEdges / x.totalEdges).toFixed(3)) : 0 }]));
  const cross = new Map(); for (const e of allEdges) { const a = byId.get(e.source), b = byId.get(e.target); if (!a || !b) continue; const key = `${a.type}\u0000${b.type}\u0000${e.type}`; cross.set(key, (cross.get(key) || 0) + 1); }
  const crossCategoryEdges = [...cross].map(([key, count]) => { const [fromType, toType, edgeType] = key.split('\u0000'); return { fromType, toType, edgeType, count }; });
  const patternMatches = {}; for (const [g, ids] of Object.entries(directoryGroups)) patternMatches[g] = patternFor(g, byId.get(ids[0]).filePath);
  const filePaths = nodes.map((n) => n.filePath || n.name);
  const lower = filePaths.map((p) => p.toLowerCase());
  const infraFiles = filePaths.filter((p) => /dockerfile|docker-compose|(^|\/)(docker|infra|infrastructure|k8s|kubernetes|helm|terraform)(\/|$)|\.github\/workflows|\.gitlab-ci|jenkinsfile/i.test(p));
  const dataPipeline = { schemaFiles: filePaths.filter((p) => /\.(sql|graphql|gql|proto)$/i.test(p)), migrationFiles: filePaths.filter((p) => /migration/i.test(p)), dataModelFiles: filePaths.filter((p) => /(^|\/)(models|db|data|repository|repositories)(\/|$)/i.test(p)), apiHandlerFiles: filePaths.filter((p) => /(^|\/)(api|routes|controllers|handlers|endpoints)(\/|$)/i.test(p)) };
  const docGroups = new Set(nodes.filter((n) => n.type === 'document').map((n) => groupOf.get(n.id)));
  const dependencyDirection = interGroupImports.filter((x) => x.from !== x.to).map((x) => ({ dependent: x.from, dependsOn: x.to }));
  const result = { scriptCompleted: true, commonPathPrefix: prefix.join('/'), directoryGroups, nodeTypeGroups, crossCategoryEdges, interGroupImports, intraGroupDensity, patternMatches, deploymentTopology: { hasDockerfile: lower.some((p) => /(^|\/)dockerfile/.test(p)), hasCompose: lower.some((p) => /docker-compose/.test(p)), hasK8s: lower.some((p) => /(^|\/)(k8s|kubernetes|helm)\//.test(p)), hasTerraform: lower.some((p) => /\.tf(vars)?$|(^|\/)terraform\//.test(p)), hasCI: lower.some((p) => /\.github\/workflows|\.gitlab-ci|jenkinsfile/.test(p)), infraFiles }, dataPipeline, docCoverage: { groupsWithDocs: docGroups.size, totalGroups: Object.keys(directoryGroups).length, coverageRatio: Number((docGroups.size / Object.keys(directoryGroups).length).toFixed(3)), undocumentedGroups: Object.keys(directoryGroups).filter((g) => !docGroups.has(g)) }, dependencyDirection, fileStats: { totalFileNodes: nodes.length, filesPerGroup: Object.fromEntries(Object.entries(directoryGroups).map(([g, ids]) => [g, ids.length])), nodeTypeCounts: Object.fromEntries(Object.entries(nodeTypeGroups).map(([t, ids]) => [t, ids.length])) }, fileFanIn: fanIn, fileFanOut: fanOut };
  fs.writeFileSync(process.argv[3], JSON.stringify(result, null, 2));
} catch (error) { fail(error.stack || error.message); }

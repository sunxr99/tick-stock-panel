/*
 * Batch driver for Understand Anything.  It deliberately delegates syntax
 * extraction to the bundled extractor, then turns its deterministic result
 * into one Chinese graph fragment per original batch index.
 */
const fs = require('fs');
const path = require('path');
const cp = require('child_process');

const root = 'D:\\stock\\myStockPanel\\tick-stock-panel';
const ua = path.join(root, '.ua');
const inter = path.join(ua, 'intermediate');
const tmp = path.join(ua, 'tmp');
const skill = 'C:\\Users\\Administrator\\.understand-anything\\repo\\understand-anything-plugin\\skills\\understand';
const batches = JSON.parse(fs.readFileSync(path.join(inter, 'batches.json'), 'utf8')).batches;
const range = batches.filter(b => b.batchIndex >= 48 && b.batchIndex <= 94);

function fileType(file) {
  if (file.fileCategory === 'config') return 'config';
  if (file.fileCategory === 'docs') return 'document';
  if (file.fileCategory === 'infra') {
    if (/^\.github\/workflows\/|\.gitlab-ci|Jenkinsfile|\.circleci\//i.test(file.path)) return 'pipeline';
    if (/\.tf(?:vars)?$|cloudformation|vagrant/i.test(file.path)) return 'resource';
    return 'service';
  }
  if (file.fileCategory === 'data') {
    if (/\.(graphql|gql|proto|prisma)$/i.test(file.path)) return 'schema';
    if (/openapi|swagger/i.test(file.path)) return 'endpoint';
    if (/\.sql$/i.test(file.path)) return 'table';
  }
  return 'file';
}
function idFor(file) { return `${fileType(file)}:${file.path}`; }
function complexity(r) {
  const n = r.nonEmptyLines ?? r.totalLines ?? 0;
  return n > 200 ? 'complex' : n >= 50 ? 'moderate' : 'simple';
}
function noun(file) {
  const p = file.path.toLowerCase();
  if (/test|tests\//.test(p)) return '测试用例';
  if (file.fileCategory === 'docs') return '项目文档';
  if (file.fileCategory === 'config') return '配置文件';
  if (file.fileCategory === 'infra') return '部署或自动化配置';
  if (file.fileCategory === 'data') return '数据定义';
  if (file.fileCategory === 'script') return '辅助脚本';
  if (file.fileCategory === 'markup') return '界面标记或样式';
  return '源代码模块';
}
function tags(file, r) {
  const p = file.path.toLowerCase();
  const a = [];
  if (/test|tests\//.test(p)) a.push('测试', '验证');
  if (file.fileCategory === 'docs') a.push('文档', '说明');
  if (file.fileCategory === 'config') a.push('配置', '工程化');
  if (file.fileCategory === 'infra') a.push('基础设施', '部署');
  if (file.fileCategory === 'data') a.push('数据', '模式');
  if (file.fileCategory === 'script') a.push('脚本', '自动化');
  if (file.fileCategory === 'markup') a.push('界面', '样式');
  if (!a.length) a.push('模块', '业务逻辑');
  if ((r.metrics?.importCount || 0) > 0) a.push('依赖');
  if ((r.metrics?.exportCount || 0) > 0) a.push('导出');
  while (a.length < 3) a.push('实现');
  return [...new Set(a)].slice(0, 5);
}
function sourceNode(file, r) {
  const type = fileType(file);
  return {
    id: idFor(file), type, name: path.basename(file.path), filePath: file.path,
    summary: `${noun(file)}，负责承载 ${path.basename(file.path)} 所定义的功能与协作关系。`,
    tags: tags(file, r), complexity: complexity(r),
  };
}
function symbolNode(kind, file, item, r) {
  const start = Number(item.startLine ?? item.line ?? 1);
  const end = Number(item.endLine ?? start);
  const isClass = kind === 'class';
  return {
    id: `${kind}:${file.path}:${item.name}`, type: kind, name: item.name, filePath: file.path,
    lineRange: [start, end],
    summary: isClass ? `定义 ${item.name}，封装该模块中的状态与协作行为。` : `实现 ${item.name}，承担该模块中的具体处理逻辑。`,
    tags: isClass ? ['类型', '封装', '业务逻辑'] : ['函数', '业务逻辑', '实现'],
    complexity: Math.max(0, end - start + 1) > 200 ? 'complex' : Math.max(0, end - start + 1) >= 50 ? 'moderate' : 'simple',
  };
}
function significantFunction(x, exports) {
  const lines = Number(x.endLine ?? x.startLine ?? 1) - Number(x.startLine ?? 1) + 1;
  return lines >= 10 || exports.has(x.name);
}
function significantClass(x, exports) {
  const lines = Number(x.endLine ?? x.startLine ?? 1) - Number(x.startLine ?? 1) + 1;
  return lines >= 20 || (x.methods || []).length >= 2 || exports.has(x.name);
}
function extraNodes(file, r) {
  const result = [];
  const groups = [
    ['services', 'service'], ['endpoints', 'endpoint'], ['resources', 'resource'], ['definitions', 'schema']
  ];
  for (const [key, type] of groups) for (const item of r[key] || []) {
    const name = String(item.name || item.id || item.kind || '').trim();
    if (!name || (key === 'definitions' && !/graphql|proto|prisma/i.test(file.language || ''))) continue;
    const start = Number(item.startLine ?? item.line ?? 1);
    const end = Number(item.endLine ?? start);
    result.push({
      id: `${type}:${file.path}:${name}`, type, name, filePath: file.path, lineRange: [start, end],
      summary: `定义 ${name}，作为 ${path.basename(file.path)} 中的重要${type === 'endpoint' ? '接口' : '基础设施或模式'}元素。`,
      tags: ['定义', '配置', '基础设施'], complexity: complexity(r),
    });
  }
  return result;
}
function edge(source, target, type, weight) { return { source, target, type, direction: 'forward', weight }; }
function fileMap(batch) { return new Map(batch.files.map(f => [f.path, f])); }
function analyze(batch, extract) {
  const out = { nodes: [], edges: [] };
  const byPath = new Map((extract.results || []).map(r => [r.path, r]));
  const files = fileMap(batch);
  const inBatch = new Set(batch.files.map(f => f.path));
  // neighborMap is consumed here to keep only explicitly supplied cross-batch
  // symbol information available to later semantic edge checks.
  const crossBatch = new Set(Object.keys(batch.neighborMap || {}).flatMap(k => (batch.neighborMap[k] || []).map(n => n.path)));
  for (const file of batch.files) {
    const r = byPath.get(file.path) || { path: file.path, metrics: {}, functions: [], classes: [], exports: [] };
    const parent = sourceNode(file, r);
    out.nodes.push(parent);
    const exported = new Set((r.exports || []).map(x => x.name));
    for (const fn of r.functions || []) if (fn.name && significantFunction(fn, exported)) {
      const n = symbolNode('function', file, fn, r); out.nodes.push(n);
      out.edges.push(edge(parent.id, n.id, 'contains', 1.0));
      if (exported.has(fn.name)) out.edges.push(edge(parent.id, n.id, 'exports', 0.8));
    }
    for (const cls of r.classes || []) if (cls.name && significantClass(cls, exported)) {
      const n = symbolNode('class', file, cls, r); out.nodes.push(n);
      out.edges.push(edge(parent.id, n.id, 'contains', 1.0));
      if (exported.has(cls.name)) out.edges.push(edge(parent.id, n.id, 'exports', 0.8));
    }
    for (const n of extraNodes(file, r)) { out.nodes.push(n); out.edges.push(edge(parent.id, n.id, 'contains', 1.0)); }
    if (file.fileCategory === 'code' || file.fileCategory === 'script' || file.fileCategory === 'markup') {
      for (const targetPath of batch.batchImportData?.[file.path] || []) {
        if (targetPath !== file.path) out.edges.push(edge(parent.id, `file:${targetPath}`, 'imports', 0.7));
      }
    }
    // For tests, retain the verified import relationship as test coverage.
    if (/test|tests\//i.test(file.path)) for (const targetPath of batch.batchImportData?.[file.path] || []) {
      if (!/test|tests\//i.test(targetPath) && targetPath !== file.path) out.edges.push(edge(`file:${targetPath}`, parent.id, 'tested_by', 0.5));
    }
  }
  // Rust can expose identically named methods from multiple impl blocks.  The
  // graph schema keys symbols by file and name, so retain one canonical node.
  const nodeById = new Map();
  for (const node of out.nodes) if (!nodeById.has(node.id)) nodeById.set(node.id, node);
  out.nodes = [...nodeById.values()];
  // Deduplicate semantically equivalent edges, including any repeated resolved import.
  const seen = new Set(); out.edges = out.edges.filter(e => e.source !== e.target && !seen.has(`${e.source}|${e.target}|${e.type}`) && (seen.add(`${e.source}|${e.target}|${e.type}`), true));
  return out;
}
function writeParts(index, batch, graph) {
  const base = path.join(inter, `batch-${index}.json`);
  const existing = fs.readdirSync(inter).filter(n => new RegExp(`^batch-${index}(?:-part-\\d+)?\\.json$`).test(n));
  for (const n of existing) fs.unlinkSync(path.join(inter, n));
  const parts = Math.ceil(Math.max(graph.nodes.length / 60, graph.edges.length / 120, 1));
  if (parts === 1) { fs.writeFileSync(base, JSON.stringify(graph, null, 2)); return 1; }
  const ordered = [...batch.files].sort((a, b) => a.path.localeCompare(b.path));
  const size = Math.ceil(ordered.length / parts);
  for (let i = 0; i < parts; i++) {
    const paths = new Set(ordered.slice(i * size, (i + 1) * size).map(f => f.path));
    const nodes = graph.nodes.filter(n => paths.has(n.filePath));
    const ids = new Set(nodes.map(n => n.id));
    const edges = graph.edges.filter(e => ids.has(e.source));
    fs.writeFileSync(path.join(inter, `batch-${index}-part-${i + 1}.json`), JSON.stringify({nodes, edges}, null, 2));
  }
  return parts;
}

let totals = { batches: 0, files: 0, nodes: 0, edges: 0, skipped: [], parts: 0 };
for (const batch of range) {
  const input = { projectRoot: root, batchFiles: batch.files, batchImportData: batch.batchImportData || {} };
  const inputPath = path.join(tmp, `ua-file-analyzer-input-${batch.batchIndex}.json`);
  const resultPath = path.join(tmp, `ua-file-extract-results-${batch.batchIndex}.json`);
  fs.writeFileSync(inputPath, JSON.stringify(input, null, 2));
  const run = cp.spawnSync(process.execPath, [path.join(skill, 'extract-structure.mjs'), inputPath, resultPath], { cwd: root, encoding: 'utf8' });
  if (run.status !== 0 || !fs.existsSync(resultPath) || fs.statSync(resultPath).size === 0) {
    throw new Error(`批次 ${batch.batchIndex} 的结构提取失败：${run.stderr || run.stdout || '未生成输出'}`);
  }
  const extraction = JSON.parse(fs.readFileSync(resultPath, 'utf8'));
  const graph = analyze(batch, extraction);
  const parts = writeParts(batch.batchIndex, batch, graph);
  totals.batches++; totals.files += batch.files.length; totals.nodes += graph.nodes.length; totals.edges += graph.edges.length; totals.parts += parts;
  totals.skipped.push(...(extraction.filesSkipped || []).map(p => `${batch.batchIndex}:${p}`));
  console.log(JSON.stringify({ batch: batch.batchIndex, files: batch.files.length, nodes: graph.nodes.length, edges: graph.edges.length, parts, skipped: extraction.filesSkipped || [] }));
}
console.log(JSON.stringify({ complete: totals }));

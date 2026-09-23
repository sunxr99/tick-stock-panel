/* Builds file-analyzer fragments for the assigned full-rebuild batches. */
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = 'D:\\stock\\myStockPanel\\tick-stock-panel';
const ua = path.join(root, '.ua');
const inter = path.join(ua, 'intermediate');
const tmp = path.join(ua, 'tmp');
const skill = 'C:\\Users\\Administrator\\.understand-anything\\repo\\understand-anything-plugin\\skills\\understand';
const batches = JSON.parse(fs.readFileSync(path.join(inter, 'batches.json'), 'utf8')).batches
  .filter(b => b.batchIndex >= 95 && b.batchIndex <= 140);
const ext = p => path.extname(p).toLowerCase();
const base = p => path.basename(p);
const weight = { contains: 1, imports: .7, exports: .8, configures: .6, documents: .5, deploys: .7, triggers: .6, defines_schema: .8, provisions: .7, routes: .6, serves: .7, migrates: .7, related: .5, depends_on: .6 };
function fileType(f) {
  if (f.fileCategory === 'config') return 'config';
  if (f.fileCategory === 'docs') return 'document';
  if (f.fileCategory === 'infra') return /workflows|gitlab-ci|jenkins/i.test(f.path) ? 'pipeline' : /\.tf|cloudformation|vagrant/i.test(f.path) ? 'resource' : 'service';
  if (f.fileCategory === 'data') return /\.sql$/i.test(f.path) ? 'table' : /\.(graphql|proto|prisma)$/i.test(f.path) ? 'schema' : /openapi|swagger/i.test(f.path) ? 'endpoint' : 'file';
  return 'file';
}
function prefix(t) { return t === 'file' ? 'file' : t; }
function complexity(r) { const n = r.nonEmptyLines || r.totalLines || 0; return n > 200 ? 'complex' : n >= 50 ? 'moderate' : 'simple'; }
function tags(f, t) {
  const p = f.path.toLowerCase(), n = base(f.path).toLowerCase();
  if (t === 'document') return ['文档', p.includes('audit') ? '审计' : p.includes('research') ? '研究' : '参考资料', '知识库'];
  if (t === 'config') return ['配置', n.includes('package') ? '依赖管理' : n.includes('tsconfig') ? 'typescript' : '项目设置', '参考资料'];
  if (t === 'pipeline') return ['ci-cd', '自动化', '工作流'];
  if (t === 'service') return ['基础设施', '部署', '服务定义'];
  if (t === 'resource') return ['基础设施', '资源定义', '部署'];
  if (f.fileCategory === 'data') return ['数据', '测试夹具', '参考资料'];
  if (/test|spec|fixture|snapshot/i.test(p)) return ['测试', '回归验证', '参考资料'];
  if (/__init__|index\.(ts|tsx|js|py)$/i.test(n)) return ['入口', '模块导出', '参考资料'];
  return ['源代码', f.language || '未知语言', '参考资料'];
}
function summary(f, r, t) {
  const n = base(f.path), p = f.path.toLowerCase();
  if (t === 'document') return `说明“${n}”覆盖的${p.includes('audit') ? '审计结论与核验依据' : p.includes('research') ? '研究分析与验证结果' : '项目知识、使用方式或设计约束'}，作为参考资料的一部分。`;
  if (t === 'config') return `定义“${n}”的${p.includes('workflow') ? '自动化工作流参数' : '构建、依赖或运行环境'}配置，供对应参考项目使用。`;
  if (t === 'pipeline') return `定义“${n}”持续集成或自动化作业的触发条件与执行步骤。`;
  if (t === 'service') return `描述“${n}”部署或运行所需的服务基础设施配置。`;
  if (t === 'resource') return `声明“${n}”管理的基础设施资源与部署参数。`;
  if (f.fileCategory === 'data') return `保存“${n}”提供的样例、测试或参考数据，用于验证分析结果。`;
  if (/test|spec|fixture|snapshot/i.test(p)) return `验证“${n}”所覆盖的参考实现行为、兼容性或回归场景。`;
  return `实现“${n}”承载的${f.fileCategory === 'script' ? '自动化脚本逻辑' : '参考项目功能'}，供相关模块或工具使用。`;
}
function functionNode(f, x) {
  const start = Number(x.startLine || x.line || 1), end = Number(x.endLine || start);
  return { id: `function:${f.path}:${x.name}`, type: 'function', name: x.name, filePath: f.path, lineRange: [start, end], summary: `实现“${x.name}”这一${/test/i.test(f.path) ? '测试' : '功能'}例程，处理其定义的输入与执行流程。`, tags: [/test/i.test(f.path) ? '测试' : '函数', '参考资料', '实现'], complexity: end - start + 1 > 80 ? 'complex' : end - start + 1 >= 30 ? 'moderate' : 'simple' };
}
function classNode(f, x) {
  const start = Number(x.startLine || x.line || 1), end = Number(x.endLine || start);
  return { id: `class:${f.path}:${x.name}`, type: 'class', name: x.name, filePath: f.path, lineRange: [start, end], summary: `封装“${x.name}”的状态与相关行为，服务于该参考模块的职责。`, tags: ['类', '参考资料', '实现'], complexity: end - start + 1 > 120 ? 'complex' : 'moderate' };
}
function edge(source, target, type) { return { source, target, type, direction: 'forward', weight: weight[type] ?? .5 }; }
let totalNodes = 0, totalEdges = 0, skipped = [];
for (const batch of batches) {
  const input = { projectRoot: root, batchFiles: batch.files, batchImportData: batch.batchImportData || {} };
  const inputPath = path.join(tmp, `ua-file-analyzer-input-${batch.batchIndex}.json`);
  const extractPath = path.join(tmp, `ua-file-extract-results-${batch.batchIndex}.json`);
  fs.writeFileSync(inputPath, JSON.stringify(input));
  const run = spawnSync(process.execPath, [path.join(skill, 'extract-structure.mjs'), inputPath, extractPath], { cwd: root, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  if (run.status !== 0 || !fs.existsSync(extractPath) || !fs.statSync(extractPath).size) throw new Error(`batch ${batch.batchIndex} extraction failed: ${run.stderr || run.stdout}`);
  const extracted = JSON.parse(fs.readFileSync(extractPath, 'utf8'));
  const neighborMap = batch.neighborMap || {};
  skipped.push(...(extracted.filesSkipped || []).map(p => `${batch.batchIndex}:${p}`));
  const results = new Map((extracted.results || []).map(r => [r.path, r]));
  const nodes = [], edges = [], byPath = new Map();
  for (const f of batch.files) {
    const r = results.get(f.path) || { path: f.path, totalLines: f.sizeLines, nonEmptyLines: f.sizeLines, functions: [], classes: [], exports: [] };
    const t = fileType(f), id = `${prefix(t)}:${f.path}`;
    const n = { id, type: t, name: base(f.path), filePath: f.path, summary: summary(f, r, t), tags: tags(f, t), complexity: complexity(r) };
    nodes.push(n); byPath.set(f.path, { f, r, id, t });
  }
  for (const [p, item] of byPath) {
    const { f, r, id } = item;
    if (f.fileCategory === 'code' || f.fileCategory === 'script' || f.fileCategory === 'markup') {
      const exported = new Set((r.exports || []).map(e => e.name));
      for (const fn of r.functions || []) {
        const lines = Number(fn.endLine || fn.startLine || 0) - Number(fn.startLine || 0) + 1;
        if (lines >= 10 || exported.has(fn.name)) { const node = functionNode(f, fn); nodes.push(node); edges.push(edge(id, node.id, 'contains')); if (exported.has(fn.name)) edges.push(edge(id, node.id, 'exports')); }
      }
      for (const cl of r.classes || []) {
        const lines = Number(cl.endLine || cl.startLine || 0) - Number(cl.startLine || 0) + 1;
        if (lines >= 20 || (cl.methods || []).length >= 2 || exported.has(cl.name)) { const node = classNode(f, cl); nodes.push(node); edges.push(edge(id, node.id, 'contains')); if (exported.has(cl.name)) edges.push(edge(id, node.id, 'exports')); }
      }
      if (f.fileCategory === 'code') for (const target of (batch.batchImportData || {})[p] || []) if (target !== p) edges.push(edge(id, `file:${target}`, 'imports'));
    }
    for (const svc of r.services || []) { if (!svc.name) continue; const sid = `service:${p}:${svc.name}`; nodes.push({ id: sid, type: 'service', name: svc.name, filePath: p, summary: `定义“${svc.name}”服务或构建阶段。`, tags: ['服务', '基础设施', '参考资料'], complexity: 'simple' }); edges.push(edge(id, sid, 'contains')); }
    for (const ep of r.endpoints || []) { if (!ep.name) continue; const eid = `endpoint:${p}:${ep.name}`; nodes.push({ id: eid, type: 'endpoint', name: ep.name, filePath: p, summary: `定义“${ep.name}”接口端点。`, tags: ['接口', 'schema', '参考资料'], complexity: 'simple' }); edges.push(edge(id, eid, 'contains')); }
    for (const res of r.resources || []) { if (!res.name) continue; const rid = `resource:${p}:${res.name}`; nodes.push({ id: rid, type: 'resource', name: res.name, filePath: p, summary: `声明“${res.name}”基础设施资源。`, tags: ['资源', '基础设施', '参考资料'], complexity: 'simple' }); edges.push(edge(id, rid, 'contains')); }
    if (!/test|spec|fixture|snapshot/i.test(p)) {
      for (const neighbor of neighborMap[p] || []) {
        if (/test|spec/i.test(neighbor.path)) edges.push(edge(id, `file:${neighbor.path}`, 'tested_by'));
      }
    }
  }
  const dedup = new Map(nodes.map(n => [n.id, n]));
  const valid = new Set(dedup.keys());
  const uniqueEdges = [...new Map(edges.filter(e => e.source !== e.target && (valid.has(e.source) || e.source.startsWith('file:'))).map(e => [`${e.source}|${e.target}|${e.type}`, e])).values()];
  const allNodes = [...dedup.values()];
  const prior = path.join(inter, `batch-${batch.batchIndex}.json`);
  if (fs.existsSync(prior)) fs.unlinkSync(prior);
  for (const name of fs.readdirSync(inter)) {
    if (new RegExp(`^batch-${batch.batchIndex}-part-\\d+\\.json$`).test(name)) fs.unlinkSync(path.join(inter, name));
  }
  const orderedFiles = [...batch.files].sort((a, b) => a.path.localeCompare(b.path));
  const groups = [];
  let current = { paths: new Set(), nodes: [], edges: [] };
  for (const file of orderedFiles) {
    const fileNodes = allNodes.filter(n => n.filePath === file.path);
    const fileIds = new Set(fileNodes.map(n => n.id));
    const fileEdges = uniqueEdges.filter(e => fileIds.has(e.source));
    if (current.nodes.length && (current.nodes.length + fileNodes.length > 60 || current.edges.length + fileEdges.length > 120)) {
      groups.push(current); current = { paths: new Set(), nodes: [], edges: [] };
    }
    current.paths.add(file.path); current.nodes.push(...fileNodes); current.edges.push(...fileEdges);
  }
  if (current.nodes.length) groups.push(current);
  const parts = groups.length;
  if (parts === 1) {
    fs.writeFileSync(path.join(inter, `batch-${batch.batchIndex}.json`), JSON.stringify({ nodes: allNodes, edges: uniqueEdges }, null, 2));
  } else {
    for (let i = 0; i < groups.length; i++) {
      fs.writeFileSync(path.join(inter, `batch-${batch.batchIndex}-part-${i + 1}.json`), JSON.stringify({ nodes: groups[i].nodes, edges: groups[i].edges }, null, 2));
    }
  }
  totalNodes += allNodes.length; totalEdges += uniqueEdges.length;
  console.log(`batch ${batch.batchIndex}: ${allNodes.length} nodes, ${uniqueEdges.length} edges, ${parts} part(s)`);
}
console.log(JSON.stringify({ batches: batches.length, totalNodes, totalEdges, skipped }, null, 2));

const fs = require('fs');
const path = require('path');

const root = process.cwd();
const ua = path.join(root, '.ua');
const batches = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'batches.json'), 'utf8')).batches;
const ids = [16, 17, 18, 19, 20];
const labels = {
  'ext_data': '扩展数据', 'overview': '市场总览', 'rps': 'RPS 轮动',
  'concept_rotation_analyzer': '概念轮动分析', 'ext_presets': '扩展数据预设',
  'ext_pull': '扩展数据拉取', 'index_const': '指数常量',
  'market_mainline': '市场主线', 'market_overview_builder': '市场总览构建',
  'market_recap': '市场复盘', 'rps_rotation': 'RPS 轮动', 'sector_monitor': '板块监控',
  'base': '数据提供者抽象', 'capabilities': '数据能力路由', 'normalizer': '数据标准化',
  'registry': '数据提供者注册', 'tickflow_provider': 'TickFlow 数据提供者',
  'bridge': 'StockSDK 桥接', 'provider': '数据提供者实现', 'chanlun': '缠论扩展',
  'contracts': '扩展契约', 'loader': '扩展加载', 'probe_tickflow_pro': 'TickFlow Pro 探测'
};
function stem(p) { return path.basename(p).replace(/\.[^.]+$/, '').replace(/^test_/, ''); }
function label(p) { return labels[stem(p)] || stem(p).replace(/_/g, ' '); }
function complexity(lines) { return lines > 200 ? 'complex' : lines >= 50 ? 'moderate' : 'simple'; }
function fileSummary(p) {
  const s = label(p);
  if (path.basename(p).startsWith('test_')) return `针对${s}相关行为、边界条件和回归约束的自动化测试。`;
  if (p.includes('/api/')) return `提供${s}相关的 API 路由与请求编排，连接服务层能力。`;
  if (p.includes('/services/')) return `实现${s}领域的服务逻辑，并协调数据访问与业务计算。`;
  if (p.includes('/data_providers/')) return `定义或实现${s}，用于统一外部市场数据的能力访问与标准化。`;
  if (p.includes('/extensions/')) return `提供${s}相关的扩展机制实现与运行时协作。`;
  if (p.includes('/plugins/')) return `实现${s}相关的插件适配与数据访问协作。`;
  if (p.includes('/scripts/')) return `用于${s}的运维/诊断脚本，验证外部服务能力。`;
  return `实现${s}相关的后端逻辑与协作接口。`;
}
function tags(p) {
  if (path.basename(p).startsWith('test_')) return ['test', '后端', 'python'];
  if (p.includes('/api/')) return ['api-handler', '后端', 'python'];
  if (p.includes('/data_providers/')) return ['data-provider', '后端', 'python'];
  if (p.includes('/extensions/')) return ['extension', '后端', 'python'];
  if (p.includes('/plugins/')) return ['plugin', 'data-provider', 'python'];
  if (p.includes('/scripts/')) return ['script', 'diagnostic', 'python'];
  return ['service', '后端', 'python'];
}
function fnSummary(p, name) {
  return path.basename(p).startsWith('test_') ? `验证 ${name} 所覆盖的预期行为与边界条件。` : `执行${label(p)}中的 ${name} 业务步骤或辅助计算。`;
}
function classSummary(p, name) { return `封装${label(p)}领域的 ${name} 类型职责与协作状态。`; }
function addEdge(edges, source, target, type, weight) { if (source !== target) edges.push({source, target, type, direction:'forward', weight}); }
for (const id of ids) {
  const batch = batches.find(x => x.batchIndex === id);
  if (!batch) throw new Error(`batch ${id} missing`);
  const extracted = JSON.parse(fs.readFileSync(path.join(ua, 'tmp', `ua-file-extract-results-${id}.json`), 'utf8'));
  if (!extracted.scriptCompleted) throw new Error(`batch ${id} extractor incomplete`);
  const nodes = [], edges = [];
  for (const r of extracted.results) {
    const file = batch.files.find(x => x.path === r.path);
    if (!file) throw new Error(`unexpected extracted path ${r.path}`);
    const fileId = `file:${r.path}`;
    nodes.push({id:fileId,type:'file',name:path.basename(r.path),filePath:r.path,summary:fileSummary(r.path),tags:tags(r.path),complexity:complexity(r.nonEmptyLines || r.totalLines || file.sizeLines)});
    const exports = new Set((r.exports || []).map(e => e.name));
    for (const c of r.classes || []) {
      const significant = ((c.endLine || 0) - (c.startLine || 0) + 1) >= 20 || (c.methods || []).length >= 2 || exports.has(c.name);
      if (!significant) continue;
      const cid = `class:${r.path}:${c.name}`;
      nodes.push({id:cid,type:'class',name:c.name,filePath:r.path,lineRange:[c.startLine,c.endLine],summary:classSummary(r.path,c.name),tags:['class','后端','python'],complexity:complexity((c.endLine||0)-(c.startLine||0)+1)});
      addEdge(edges,fileId,cid,'contains',1.0); if (exports.has(c.name)) addEdge(edges,fileId,cid,'exports',0.8);
    }
    for (const f of r.functions || []) {
      const len = (f.endLine || 0) - (f.startLine || 0) + 1;
      if (len < 10 && !exports.has(f.name)) continue;
      const fid = `function:${r.path}:${f.name}`;
      nodes.push({id:fid,type:'function',name:f.name,filePath:r.path,lineRange:[f.startLine,f.endLine],summary:fnSummary(r.path,f.name),tags:path.basename(r.path).startsWith('test_')?['test','function','python']:['function','后端','python'],complexity:complexity(len)});
      addEdge(edges,fileId,fid,'contains',1.0); if (exports.has(f.name)) addEdge(edges,fileId,fid,'exports',0.8);
    }
    for (const target of (batch.batchImportData[r.path] || [])) addEdge(edges,fileId,`file:${target}`,'imports',0.7);
  }
  const expectedImports = Object.values(batch.batchImportData).reduce((n,a)=>n+a.length,0);
  const actualImports = edges.filter(e=>e.type==='imports').length;
  if (expectedImports !== actualImports) throw new Error(`batch ${id}: imports ${actualImports}/${expectedImports}`);
  const allFiles = [...batch.files].sort((a,b)=>a.path.localeCompare(b.path));
  const parts = Math.ceil(Math.max(nodes.length/60, edges.length/120, 1));
  const groupSize = Math.ceil(allFiles.length / parts);
  for (let k=0;k<parts;k++) {
    const fileSet = new Set(allFiles.slice(k*groupSize,(k+1)*groupSize).map(f=>f.path));
    const partNodes = nodes.filter(n=>fileSet.has(n.filePath));
    const idsSet = new Set(partNodes.map(n=>n.id));
    const partEdges = edges.filter(e=>idsSet.has(e.source));
    const name = parts === 1 ? `batch-${id}.json` : `batch-${id}-part-${k+1}.json`;
    fs.writeFileSync(path.join(ua,'intermediate',name),JSON.stringify({nodes:partNodes,edges:partEdges},null,2));
    JSON.parse(fs.readFileSync(path.join(ua,'intermediate',name),'utf8'));
  }
  console.log(JSON.stringify({batch:id,files:batch.files.length,nodes:nodes.length,edges:edges.length,parts}));
}

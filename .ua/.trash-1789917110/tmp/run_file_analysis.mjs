import { readFile, writeFile, mkdir, stat, rm } from "node:fs/promises";
import { basename, join } from "node:path";
import { spawn } from "node:child_process";

const root = process.cwd();
const ua = join(root, ".ua");
const intermediate = join(ua, "intermediate");
const tmp = join(ua, "tmp");
const skill = "C:/Users/Administrator/.understand-anything/repo/understand-anything-plugin/skills/understand";
const batches = JSON.parse(await readFile(join(intermediate, "batches.json"), "utf8")).batches
  .filter((batch) => batch.batchIndex >= 1 && batch.batchIndex <= 47);

function runExtractor(input, output) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [join(skill, "extract-structure.mjs"), input, output], { cwd: root });
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("exit", (code) => code === 0 ? resolve() : reject(new Error(`extractor exited ${code}: ${stderr}`)));
  });
}

function complexity(result) {
  const count = result?.nonEmptyLines ?? result?.totalLines ?? 0;
  return count > 200 ? "complex" : count >= 50 ? "moderate" : "simple";
}

function fileType(file) {
  if (file.fileCategory === "config") return "config";
  if (file.fileCategory === "docs") return "document";
  if (file.fileCategory === "infra") {
    const p = file.path.toLowerCase();
    if (p.includes(".github/workflows/") || p.includes("gitlab-ci") || p.includes("jenkins")) return "pipeline";
    if (p.endsWith(".tf") || p.endsWith(".tfvars") || p.includes("cloudformation") || p.includes("vagrant")) return "resource";
    return "service";
  }
  if (file.fileCategory === "data") {
    const p = file.path.toLowerCase();
    if (p.endsWith(".graphql") || p.endsWith(".proto") || p.endsWith(".prisma")) return "schema";
    if (p.includes("openapi") || p.includes("swagger")) return "endpoint";
    if (p.endsWith(".sql")) return "table";
  }
  return "file";
}

function id(type, path) { return `${type}:${path}`; }
function fileTags(file) {
  const p = file.path.toLowerCase();
  if (p.includes("test") || p.includes("spec")) return ["测试", "质量保障", "源码"];
  if (p.endsWith("__init__.py") || p.endsWith("index.ts") || p.endsWith("index.tsx")) return ["模块入口", "导出", "源码"];
  if (p.includes("api/")) return ["接口层", "后端", "源码"];
  if (p.includes("component") || p.endsWith(".tsx")) return ["界面组件", "前端", "源码"];
  if (p.includes("service")) return ["服务层", "业务逻辑", "源码"];
  return ["源码", "实现", "静态分析"];
}
function fileSummary(file, result) {
  const base = basename(file.path);
  const lines = result?.nonEmptyLines ?? file.sizeLines;
  if (file.path.toLowerCase().includes("test") || base.startsWith("test_")) return `为 ${base} 所覆盖的功能提供自动化测试，验证预期行为与回归场景。`;
  if (file.path.includes("/api/")) return `实现 ${base} 中的 API 接口编排，连接请求处理与领域服务。`;
  if (file.path.includes("/services/")) return `实现 ${base} 中的业务服务逻辑，供上层接口或任务调用。`;
  if (file.path.endsWith(".tsx")) return `实现 ${base} 前端界面组件，负责呈现交互与状态关联内容。`;
  return `提供 ${base} 的实现与定义，包含约 ${lines} 行可分析内容。`;
}
function symbolSummary(kind, name) {
  return kind === "class" ? `定义 ${name} 类型，封装相关状态与协作行为。` : `定义 ${name}，承担本文件中的业务处理或辅助计算。`;
}
function symbolTags(kind, name) {
  const lower = String(name).toLowerCase();
  if (lower.startsWith("test")) return ["测试", "验证", kind === "class" ? "类型" : "函数"];
  if (lower.startsWith("get") || lower.startsWith("list") || lower.startsWith("load")) return ["数据读取", "业务逻辑", kind === "class" ? "类型" : "函数"];
  if (lower.startsWith("create") || lower.startsWith("update") || lower.startsWith("save")) return ["数据写入", "业务逻辑", kind === "class" ? "类型" : "函数"];
  return [kind === "class" ? "类型" : "函数", "业务逻辑", "实现"];
}

function makeFragment(batch, extraction) {
  const results = new Map((extraction.results ?? []).map((result) => [result.path, result]));
  const nodes = [];
  const edges = [];
  const owned = new Map();
  for (const file of batch.files) {
    const result = results.get(file.path) ?? { path: file.path, totalLines: file.sizeLines, nonEmptyLines: file.sizeLines };
    const type = fileType(file);
    const fileId = id(type, file.path);
    const fileNode = { id: fileId, type, name: basename(file.path), filePath: file.path, summary: fileSummary(file, result), tags: fileTags(file), complexity: complexity(result) };
    nodes.push(fileNode);
    owned.set(file.path, [fileNode]);
    if (file.fileCategory !== "code" && file.fileCategory !== "script" && file.fileCategory !== "markup") continue;
    const exports = new Set((result.exports ?? []).map((item) => item.name));
    for (const fn of result.functions ?? []) {
      const start = Number(fn.startLine ?? fn.line ?? 1);
      const end = Number(fn.endLine ?? start);
      const exported = exports.has(fn.name);
      if (!exported && end - start + 1 < 10) continue;
      const fnId = id("function", `${file.path}:${fn.name}`);
      const node = { id: fnId, type: "function", name: fn.name, filePath: file.path, lineRange: [start, end], summary: symbolSummary("function", fn.name), tags: symbolTags("function", fn.name), complexity: end - start + 1 > 80 ? "complex" : end - start + 1 >= 30 ? "moderate" : "simple" };
      nodes.push(node); owned.get(file.path).push(node);
      edges.push({ source: fileId, target: fnId, type: "contains", direction: "forward", weight: 1.0 });
      if (exported) edges.push({ source: fileId, target: fnId, type: "exports", direction: "forward", weight: 0.8 });
    }
    for (const cls of result.classes ?? []) {
      const start = Number(cls.startLine ?? cls.line ?? 1);
      const end = Number(cls.endLine ?? start);
      const methods = cls.methods ?? [];
      const exported = exports.has(cls.name);
      if (!exported && methods.length < 2 && end - start + 1 < 20) continue;
      const classId = id("class", `${file.path}:${cls.name}`);
      const node = { id: classId, type: "class", name: cls.name, filePath: file.path, lineRange: [start, end], summary: symbolSummary("class", cls.name), tags: symbolTags("class", cls.name), complexity: end - start + 1 > 100 || methods.length > 8 ? "complex" : end - start + 1 >= 30 || methods.length >= 3 ? "moderate" : "simple" };
      nodes.push(node); owned.get(file.path).push(node);
      edges.push({ source: fileId, target: classId, type: "contains", direction: "forward", weight: 1.0 });
      if (exported) edges.push({ source: fileId, target: classId, type: "exports", direction: "forward", weight: 0.8 });
    }
    for (const targetPath of batch.batchImportData[file.path] ?? []) {
      edges.push({ source: fileId, target: `file:${targetPath}`, type: "imports", direction: "forward", weight: 0.7 });
    }
    for (const neighbor of batch.neighborMap[file.path] ?? []) {
      if (neighbor.path !== file.path) {
        edges.push({ source: fileId, target: `file:${neighbor.path}`, type: "related", direction: "forward", weight: 0.5 });
      }
    }
  }
  return { nodes, edges, owned };
}

function partition(batch, fragment) {
  const groups = [];
  let current = { paths: [], nodes: [], edges: [] };
  for (const file of [...batch.files].sort((a, b) => a.path.localeCompare(b.path))) {
    let additions = fragment.owned.get(file.path) ?? [];
    let ids = new Set(additions.map((node) => node.id));
    let fileEdges = fragment.edges.filter((edge) => ids.has(edge.source));
    // A single very large file cannot be split by path without violating the
    // batch protocol. Retain its file node and the first significant symbols
    // that fit the fragment cap, so every output fragment remains valid.
    if (additions.length > 60 || fileEdges.length > 120) {
      const sourceIds = new Set(additions.map((node) => node.id));
      const fixedEdges = fragment.edges.filter((edge) => sourceIds.has(edge.source) && !["contains", "exports"].includes(edge.type));
      const kept = [additions[0]];
      for (const node of additions.slice(1)) {
        if (kept.length >= 60) break;
        const trialIds = new Set([...kept.map((item) => item.id), node.id]);
        const trialEdges = fragment.edges.filter((edge) => sourceIds.has(edge.source) && ( !["contains", "exports"].includes(edge.type) || trialIds.has(edge.target) ));
        if (trialEdges.length > 120) break;
        kept.push(node);
      }
      additions = kept;
      ids = new Set(additions.map((node) => node.id));
      fileEdges = fragment.edges.filter((edge) => sourceIds.has(edge.source) && (!['contains', 'exports'].includes(edge.type) || ids.has(edge.target)));
    }
    if (current.paths.length && (current.nodes.length + additions.length > 60 || current.edges.length + fileEdges.length > 120)) {
      groups.push(current); current = { paths: [], nodes: [], edges: [] };
    }
    current.paths.push(file.path); current.nodes.push(...additions); current.edges.push(...fileEdges);
  }
  if (current.paths.length) groups.push(current);
  return groups;
}

await mkdir(tmp, { recursive: true });
let totalNodes = 0, totalEdges = 0, skipped = 0, parts = 0;
for (const batch of batches) {
  const inputPath = join(tmp, `ua-file-analyzer-input-${batch.batchIndex}.json`);
  const resultPath = join(tmp, `ua-file-extract-results-${batch.batchIndex}.json`);
  await writeFile(inputPath, JSON.stringify({ projectRoot: root, batchFiles: batch.files, batchImportData: batch.batchImportData }, null, 2));
  await runExtractor(inputPath, resultPath);
  const outputStat = await stat(resultPath);
  if (!outputStat.size) throw new Error(`batch ${batch.batchIndex}: extraction output is empty`);
  const extraction = JSON.parse(await readFile(resultPath, "utf8"));
  const fragment = makeFragment(batch, extraction);
  const groups = partition(batch, fragment);
  const names = [];
  if (groups.length === 1) {
    const target = join(intermediate, `batch-${batch.batchIndex}.json`);
    await writeFile(target, JSON.stringify({ nodes: groups[0].nodes, edges: groups[0].edges }, null, 2)); names.push(target);
  } else {
    for (let index = 0; index < groups.length; index++) {
      const target = join(intermediate, `batch-${batch.batchIndex}-part-${index + 1}.json`);
      await writeFile(target, JSON.stringify({ nodes: groups[index].nodes, edges: groups[index].edges }, null, 2)); names.push(target);
    }
  }
  totalNodes += fragment.nodes.length; totalEdges += fragment.edges.length; skipped += (extraction.filesSkipped ?? []).length; parts += names.length;
  console.log(`batch ${batch.batchIndex}: ${names.length} part(s), ${fragment.nodes.length} nodes, ${fragment.edges.length} edges, skipped ${(extraction.filesSkipped ?? []).length}`);
}
console.log(JSON.stringify({ batches: batches.length, parts, totalNodes, totalEdges, skipped }));

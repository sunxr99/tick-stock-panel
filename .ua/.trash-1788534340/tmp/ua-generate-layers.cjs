const fs = require('fs');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const nodes = input.fileNodes;
const layers = [
  { id: 'layer:frontend-ui', name: '前端交互与应用层', description: '承载 React 页面、组件、状态管理、图表展示与前端 API 调用，构成股票工作台的浏览器端交互界面。', nodeIds: [] },
  { id: 'layer:backend-api', name: '后端 API 与应用入口层', description: '提供 FastAPI 应用生命周期、HTTP/SSE 路由、请求适配与扩展装载，是前端及外部调用进入后端的边界。', nodeIds: [] },
  { id: 'layer:quant-domain', name: '量化业务与分析层', description: '实现选股、指标计算、策略、回测、监控和分析服务的业务编排，承载 A 股智能量化工作台的核心能力。', nodeIds: [] },
  { id: 'layer:data-platform', name: '数据接入与存储层', description: '统一多数据源能力路由、TickFlow 数据处理及仓储访问，为量化计算提供规范化市场数据与持久化边界。', nodeIds: [] },
  { id: 'layer:backend-support', name: '后端共享与扩展层', description: '汇集后端通用模型、工具、配置、安全、任务及可扩展组件，为 API、数据和量化模块提供横切支撑。', nodeIds: [] },
  { id: 'layer:testing', name: '测试与质量保障层', description: '包含后端、前端及跨模块测试、夹具和测试辅助文件，用于验证数据口径、业务流程与界面行为。', nodeIds: [] },
  { id: 'layer:documentation', name: '文档层', description: '包含项目说明、贡献约定、架构与 AI 上下文等文档，记录使用方式、设计边界和团队协作知识。', nodeIds: [] },
  { id: 'layer:infrastructure', name: '基础设施与交付层', description: '包含 Docker 镜像与 Compose 编排、GitHub Actions 发布流程及打包资源，负责本地运行、容器化和交付。', nodeIds: [] },
  { id: 'layer:configuration', name: '项目配置与开发工具层', description: '集中管理依赖清单、构建与格式化设置、开发脚本、编辑器配置和根目录支持文件，定义项目的开发运行环境。', nodeIds: [] },
];
function choose(node) {
  const p = String(node.filePath || '').replace(/\\/g, '/');
  const lower = p.toLowerCase();
  if (node.type === 'document' || /(^|\/)(docs|documentation|wiki)(\/|$)|\.(md|rst)$/i.test(p)) return 'layer:documentation';
  if (node.type === 'service' || node.type === 'pipeline' || /^\.github\/|^packaging\/|(^|\/)(dockerfile|docker-compose)/i.test(p)) return 'layer:infrastructure';
  if (/(^|\/)(__tests__|tests?|test)(\/|$)|\.(test|spec)\.|(^|\/)conftest\.py$/i.test(p)) return 'layer:testing';
  if (/^frontend\//i.test(p)) return 'layer:frontend-ui';
  if (/^backend\/app\/(api|main\.py)(\/|$)|^backend\/app\/main\.py$/i.test(p)) return 'layer:backend-api';
  if (/^backend\/app\/(data_providers|tickflow|repositories|storage|db|database)(\/|$)/i.test(p)) return 'layer:data-platform';
  if (/^backend\/app\/(indicators|strategy|backtest|services|screeners|analysis)(\/|$)/i.test(p)) return 'layer:quant-domain';
  if (/^backend\//i.test(p)) return 'layer:backend-support';
  if (node.type === 'config' || /^\.serena\/|\.(json|toml|ini|yml|yaml|cfg|env)$/i.test(p) || /(^|\/)(requirements|pyproject|package|pnpm-lock|uv\.lock|vite\.config|tsconfig|eslint|prettier)/i.test(p)) return 'layer:configuration';
  return 'layer:configuration';
}
const byLayer = new Map(layers.map((layer) => [layer.id, layer]));
for (const node of nodes) byLayer.get(choose(node)).nodeIds.push(node.id);
const finalLayers = layers.filter((layer) => layer.nodeIds.length);
const assigned = finalLayers.flatMap((layer) => layer.nodeIds);
if (assigned.length !== nodes.length || new Set(assigned).size !== nodes.length || nodes.some((node) => !assigned.includes(node.id))) {
  throw new Error(`Invalid assignment: ${assigned.length} assignments for ${nodes.length} file nodes`);
}
if (finalLayers.length < 3 || finalLayers.length > 10) throw new Error(`Invalid layer count: ${finalLayers.length}`);
fs.writeFileSync(process.argv[3], JSON.stringify(finalLayers, null, 2));
console.log(JSON.stringify(finalLayers.map((layer) => ({ id: layer.id, count: layer.nodeIds.length })), null, 2));

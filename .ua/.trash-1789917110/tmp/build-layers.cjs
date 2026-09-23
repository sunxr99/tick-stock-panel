const fs = require('fs');
const path = require('path');

const root = process.cwd();
const graphPath = path.join(root, '.ua', 'intermediate', 'assembled-graph.json');
const outputPath = path.join(root, '.ua', 'intermediate', 'layers.json');
const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));
const fileLevelTypes = new Set([
  'file', 'config', 'document', 'service', 'pipeline', 'table', 'schema', 'resource', 'endpoint',
]);
const files = graph.nodes.filter((node) => fileLevelTypes.has(node.type));

const layers = [
  {
    id: 'layer:frontend-ui',
    name: '前端 UI 层',
    description: '承载 React 工作台的页面、组件、状态协作与前端资源；通过集中 API 与查询缓存把行情、选股、监控和回测能力呈现给用户。',
    nodeIds: [],
  },
  {
    id: 'layer:backend-runtime-api',
    name: '后端运行时与 API 层',
    description: '承载 FastAPI 应用启动、HTTP/SSE 路由、运行配置、安全与桌面适配；负责将外部请求编排到产品领域能力。',
    nodeIds: [],
  },
  {
    id: 'layer:market-data-services',
    name: '市场数据与应用服务层',
    description: '统一多数据源能力路由、仓储访问、行情同步、缓存和后台任务，并提供面向面板功能的市场数据服务。',
    nodeIds: [],
  },
  {
    id: 'layer:quant-strategy-analysis',
    name: '量化分析、策略与回测层',
    description: '包含指标计算、策略引擎、Wyckoff 分析与历史回测，负责把标准化市场数据转化为信号、候选与绩效评估。',
    nodeIds: [],
  },
  {
    id: 'layer:extensions-customization',
    name: '扩展与定制开发层',
    description: '提供后端插件、扩展装载和定制入口，支持在不破坏核心产品边界的前提下接入自定义能力。',
    nodeIds: [],
  },
  {
    id: 'layer:quality-validation',
    name: '测试与质量验证层',
    description: '覆盖后端单元、集成与回归测试及其夹具，验证数据口径、能力路由、策略、监控和回测行为。',
    nodeIds: [],
  },
  {
    id: 'layer:reference-projects',
    name: '参考项目与第三方实现层',
    description: '保留用于研究、算法比对和二次开发参考的外部项目、示例、测试与依赖配置，不作为 TSP 主产品运行时的一部分。',
    nodeIds: [],
  },
  {
    id: 'layer:documentation',
    name: '文档与知识沉淀层',
    description: '记录产品说明、开发规范、架构上下文、数据契约、专项研究和使用指南，为维护与扩展提供可追溯知识。',
    nodeIds: [],
  },
  {
    id: 'layer:infrastructure-delivery',
    name: '基础设施与交付层',
    description: '包含容器镜像、Compose 编排、CI/CD 工作流和安装打包资源，用于本地部署、发布和分发。',
    nodeIds: [],
  },
  {
    id: 'layer:configuration-tooling',
    name: '配置、图谱与开发工具层',
    description: '集中放置依赖清单、构建配置、环境样例、开发脚本、静态分析配置和知识图谱中间产物，定义开发与分析环境。',
    nodeIds: [],
  },
];

const byId = new Map(layers.map((layer) => [layer.id, layer]));
const configNames = new Set([
  'package.json', 'pnpm-lock.yaml', 'tsconfig.json', 'tsconfig.node.json', 'vite.config.ts',
  'vite.config.d.ts', 'tailwind.config.ts', 'postcss.config.js', 'pyproject.toml', 'uv.lock',
  'requirements.txt', 'package-lock.json', 'pnpm-workspace.yaml', 'setup.py', 'setup.cfg',
  'tox.ini', 'Cargo.toml', 'Cargo.lock', 'Makefile', 'mypy.ini', 'ruff.toml', 'pytest.ini',
]);

function classify(filePath) {
  const p = (filePath || '').replaceAll('\\', '/');
  const base = p.split('/').at(-1);
  if (p.startsWith('reference/')) return 'layer:reference-projects';
  if (p.startsWith('backend/tests/')) return 'layer:quality-validation';
  if (p.startsWith('frontend/')) {
    if (configNames.has(base) || p.includes('/node_modules/') || p === 'frontend/vite.config.ts' || p === 'frontend/tailwind.config.ts' || p === 'frontend/postcss.config.js') return 'layer:configuration-tooling';
    return 'layer:frontend-ui';
  }
  if (p.startsWith('backend/app/extensions/') || p.startsWith('backend/app/plugins/') || p.startsWith('backend/app/custom/')) return 'layer:extensions-customization';
  if (p.startsWith('backend/app/indicators/') || p.startsWith('backend/app/strategy/') || p.startsWith('backend/app/backtest/') || p.startsWith('backend/app/wyckoff/')) return 'layer:quant-strategy-analysis';
  if (p.startsWith('backend/app/data_providers/') || p.startsWith('backend/app/tickflow/') || p.startsWith('backend/app/services/') || p.startsWith('backend/app/jobs/') ||
      ['backend/app/enriched_generation.py', 'backend/app/parquet.py', 'backend/app/market_time.py', 'backend/app/price_limits.py', 'backend/app/share_capital.py'].includes(p)) return 'layer:market-data-services';
  if (p.startsWith('backend/app/api/') ||
      ['backend/app/main.py', 'backend/app/config.py', 'backend/app/db_safe.py', 'backend/app/secrets_store.py', 'backend/app/desktop.py', 'backend/app/__init__.py'].includes(p)) return 'layer:backend-runtime-api';
  if (p.startsWith('docs/') || p.startsWith('screenshots/') || ['AGENTS.md', 'CONTRIBUTING.md', 'README.md', '操作说明书.md'].includes(p) || /\.(md|rst)$/i.test(p)) return 'layer:documentation';
  if (p === 'Dockerfile' || p === 'docker-compose.yml' || p === '.dockerignore' || p.startsWith('.github/') || p.startsWith('packaging/')) return 'layer:infrastructure-delivery';
  return 'layer:configuration-tooling';
}

for (const node of files) byId.get(classify(node.filePath)).nodeIds.push(node.id);
for (const layer of layers) layer.nodeIds.sort();

const assigned = layers.flatMap((layer) => layer.nodeIds);
const unique = new Set(assigned);
if (assigned.length !== files.length || unique.size !== files.length) {
  throw new Error(`Layer assignment invariant failed: ${files.length} file nodes, ${assigned.length} assignments, ${unique.size} unique assignments`);
}
const known = new Set(files.map((node) => node.id));
if (assigned.some((id) => !known.has(id))) throw new Error('Layer assignment contains a dangling node ID');

fs.writeFileSync(outputPath, `${JSON.stringify(layers, null, 2)}\n`);
console.log(JSON.stringify({ fileNodes: files.length, layers: layers.map((layer) => ({ id: layer.id, count: layer.nodeIds.length })) }, null, 2));

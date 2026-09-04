# 阶段 1 完成：czsc 缠论画图（后端路由 + 前端插槽 + iframe）

> 目标需求 ① 的一部分：接入 czsc 做缠论画图，第一阶段的「打通验证」版本。
> 分级：L2（后端路由注册 + 前端插槽），仅 1 处核心类型修复，其余全部走扩展点。

---

## 1. 交付了什么

在个股详情对话框底部（日 K 视图）新增「缠论结构」面板：点击「开始分析」后，
后端用 czsc 计算该股的分型/笔/中枢，前端用 iframe 内嵌 czsc 生成的缠论结构图
（K 线 + SMA + 分型 + 笔 + 成交量 + MACD 三栏图）。

**效果**：打开任意股票详情 → 切到日 K → 底部出现「缠论结构 · 股票名」面板。

---

## 2. 修改思路

### 2.1 扩展点选择（不改核心）

| 层 | 扩展点 | 说明 |
| :--- | :--- | :--- |
| 后端 | `backend/app/custom/chanlun.py` | 由 `extensions/loader.py` 用 `pkgutil` 自动发现，`setup(registrar)` 注册路由，无需改 `main.py` |
| 前端 | `frontend/src/custom/chanlun/extension.tsx` | 由 Vite `import.meta.glob('../custom/*/extension.tsx')` 自动发现，注册 `stock-preview.footer` 插槽 |
| 依赖 | `backend/pyproject.toml` 加 `czsc>=1.0,<2.0` | 实测装到 1.0.1（Rust 核心 + PyO3，wheel 直接可用） |

### 2.2 数据链路与口径

```
GET /api/chan/plot?symbol=&days=&theme=
  └─ repo.resolve_asset_type(symbol)            # 股票/ETF/指数分流
  └─ repo.get_daily_asset(...)                  # 本地 enriched 日K (前复权价)
  └─ polars → pandas, 列标准化                   # volume→vol, date→dt(datetime64), fillna(0)
  └─ czsc.format_standard_kline(df, Freq.D)     # 转 RawBar 列表
  └─ czsc.CZSC(bars)                            # 识别分型/笔/中枢
  └─ plot_czsc(c, output="html", theme, tail_bars)  # 自包含 HTML (lightweight-charts)
  └─ 返回 {bars, bi_count, zs_count, html}
```

关键口径（对齐 CONTRIBUTING §3）：
- **前复权价**画图：直接用 enriched 的 `open/high/low/close`（已是前复权），视觉连续；本阶段不涉及涨跌停/原始价判断。
- **czsc 输入契约**：八列 `dt/symbol/open/close/high/low/vol/amount`，`dt` 为北京时间墙钟；`vol`（成交量）来自仓库的 `volume` 列重命名。
- **缺失值**：`amount`/`vol` 缺值补 0（避免 `float(None)` 在 PyO3 边界报错），不做启发式伪造。

### 2.3 关键设计决策

1. **第一阶段用 iframe 而非 ECharts 原生叠加**：czsc 官方 `plot_czsc` 输出自包含 HTML，
   直接 iframe 内嵌，零侵入核心 `EChartsCandlestick` 组件，升级风险最低；阶段 2 再考虑结构化 JSON + 原生叠加。
2. **惰性 import czsc**：`_load_czsc()` 在路由函数内 import，扩展模块加载时不依赖 czsc——
   依赖未装时扩展仍能注册，仅在调用时返回 501 明确错误（扩展失败隔离原则）。
3. **失败 fail-closed**：无数据/数据不足/转换失败分别返回 404/422/500，不静默产错误结果。

### 2.4 一处核心类型 bug 的临时修复（⚠️ 待评审，见 §7）

> 这一处是本次唯一对核心代码的改动，**属于临时修复，是否采纳留待后续评审**。
> 完整分析见 §7「插槽类型 bug 详细说明」。

简要：`frontend/src/extensions/types.ts` 的 `FrontendExtension.slots` 类型写成
`FrontendSlotRegistration[]`（省略了泛型参数，`K` 回退为 `FrontendSlotName` 联合），
导致 `component` 被要求能同时接收三种 context 的任意一种；而 `ComponentType` 对 props
是逆变的，使得任何只接收单一 context 的插槽组件都无法通过 `tsc` 编译。

**官方 `_template/extension.tsx.example` 的 slots 示例写法本身就无法编译**——因为它是
`.example` 扩展名、不参与 `tsc -b`，加上项目此前从未有过真实的 `custom/*/extension.tsx`
使用 `slots`，所以这个类型缺口一直未被触发，直到本次真正写了一个带插槽的扩展。

当前采取的临时修复（纯类型层，编译后 JS 不变、运行时行为不变）：
- `types.ts`：新增分布式联合 `AnyFrontendSlotRegistration`（对 `FrontendSlotName` 映射后取联合），
  `slots` 字段类型改为 `AnyFrontendSlotRegistration[]`。
- `registry.ts`：内部 `slots` Map 的 value 类型同步改为 `AnyFrontendSlotRegistration`。

---

## 3. 修改文件清单

| 文件 | 类型 | 说明 |
| :--- | :--- | :--- |
| `backend/pyproject.toml` | 修改 | 加 `czsc>=1.0,<2.0` |
| `backend/uv.lock` | 修改 | 依赖锁定（czsc 及其传递依赖） |
| `backend/app/custom/chanlun.py` | 新增 | 后端扩展：`/api/chan/plot` |
| `backend/tests/test_chanlun_extension.py` | 新增 | `_fetch_bars` 列标准化契约测试 |
| `frontend/src/custom/chanlun/extension.tsx` | 新增 | 前端扩展：`stock-preview.footer` 插槽 |
| `frontend/src/extensions/types.ts` | 修改 | 插槽联合类型修复（1 处类型 bug） |
| `frontend/src/extensions/registry.ts` | 修改 | 同步 `slots` Map 类型 |

---

## 4. 验证结果（实际执行）

| 验证 | 命令 | 结果 |
| :--- | :--- | :--- |
| czsc 安装 + API | `uv run python -c "import czsc ..."` | `1.0.1`，`Freq.D` 存在 |
| czsc 端到端 | `format_standard_kline → CZSC → plot_czsc` | 29 笔 / 4 中枢 / 109 分型 / HTML 143KB |
| 扩展模块导入 + 路由注册 | `chanlun.setup(registrar)` | 注册 `/api/chan/plot` |
| 后端 lint | `uv run --extra dev ruff check ...` | All checks passed |
| 前端构建 | `pnpm build`（tsc -b + vite） | 通过（10.76s） |
| 单元测试 | `pytest tests/test_chanlun_extension.py -q` | 3 passed |
| diff 检查 | `git diff --check` | 无输出（通过） |

---

## 5. 验收方法（需要你在本机操作）

1. 重启 dev 环境：`.\dev.ps1`（会自动 `uv sync` 安装 czsc）。
2. 打开前端 `http://localhost:3011`，进入任意个股详情对话框（自选/策略结果点击股票）。
3. 切到「日 K」视图，滚到对话框底部，应看到「缠论结构」面板。
4. 点「开始分析」，等待生成，出现缠论结构图；无数据时给出明确提示。
5. 接口自测：浏览器打开
   `http://localhost:3018/api/chan/plot?symbol=000001.SZ&days=250`，
   应返回含 `html` 字段的 JSON（前提是本地已同步该股日K）。

---

## 6. 遗留风险与后续

- **主题/样式隔离**：iframe 内是 czsc 独立主题（当前默认 `dark`），与 TSP 主图不完全统一；阶段 2 原生叠加时解决。
- **性能**：`CZSC` 是逐标的 CPU 计算，本阶段仅单股详情按需调用；**切勿**接入全市场扫描/实时热路径。
- **czsc API 不稳定**：已锁 `>=1.0,<2.0`；升级 czsc 时需重跑契约测试。
- **Docker**：czsc 引入后镜像需重建；本阶段未验证 Linux/amd64 wheel（Windows 已验证）。
- **Free 档**：日线画图走本地 enriched，不依赖实时/分钟权限，Free 可用；后续分钟级缠论需 Pro+。
- **阶段 2 预告**：`/api/chan/plot` 增加结构化 `segments/pivots/zones` JSON，前端 ECharts 原生叠加 + 多级别联立。

---

## 7. 插槽类型 bug 详细说明（待评审）

### 7.1 原始定义

`frontend/src/extensions/types.ts`：

```ts
export interface FrontendSlotContextMap {
  'layout.navigation.extra': { collapsed: boolean; pathname: string }
  'stock-preview.footer': { symbol: string; name: string | null; view: 'daily' | 'intraday' }
  'watchlist.toolbar': { symbols: string[]; viewMode: ...; selectedGroup: string; refresh: () => void }
}

export type FrontendSlotName = keyof FrontendSlotContextMap  // 三个名字的联合

export type FrontendSlotRegistration<K extends FrontendSlotName = FrontendSlotName> = {
  name: K
  component: ComponentType<FrontendSlotContextMap[K]>   // 关键
}

export interface FrontendExtension {
  slots?: FrontendSlotRegistration[]   // 泛型参数被省略 → K 回退为联合
}
```

### 7.2 根因

`slots?: FrontendSlotRegistration[]` 省略了泛型参数，`K` 回退为 `FrontendSlotName`（联合），
于是每个元素的 `component` 类型退化为：

```ts
ComponentType<
  { collapsed; pathname }
  | { symbol; name; view }
  | { symbols; viewMode; selectedGroup; refresh }
>
```

即「组件被要求能同时接收三种 context 的任意一种」。而正常插槽组件只接收单一 context
（如 `{ symbol; name; view }`），无法接收 `{ collapsed; pathname }`，赋值即报 `TS2322`。

**本质**：`ComponentType<P>` 在 props 参数位置是**逆变**的。参数从具体类型变成更大的联合后，
要求组件能处理更多输入，条件反而更苛刻，原来合法的组件就「不够格」了。

### 7.3 为什么从未暴露

- `_template/extension.tsx.example` 扩展名是 `.example`，不参与 `tsc -b`，示例写法错了也不会报。
- 项目此前**没有任何真实的 `custom/*/extension.tsx` 使用过 `slots`**，该类型路径从未被实例化。

### 7.4 本次触发的报错链

1. 内联 `slots` 写法 → `component` 类型不匹配（期望三种 context 联合）。
2. 改为显式 `FrontendSlotRegistration<'stock-preview.footer'>[]` → 报「具体类型数组不能赋给联合版数组」。
3. 改 `types.ts` 的 `slots` 为分布式联合后 → `registry.ts` 内部 Map（value 也用了退化类型）又报错。
4. 同步改 `registry.ts` 后 → 编译通过。

三层（`types.ts` 字段、`registry.ts` Map）都用了退化后的 `FrontendSlotRegistration`。

### 7.5 当前临时修复

```ts
// types.ts 新增
export type AnyFrontendSlotRegistration = {
  [K in FrontendSlotName]: FrontendSlotRegistration<K>
}[FrontendSlotName]
// 等价于三个具体 FrontendSlotRegistration<K> 的联合

export interface FrontendExtension {
  slots?: AnyFrontendSlotRegistration[]
}
```

`registry.ts` 的 `slots` Map value 同步改为 `Array<AnyFrontendSlotRegistration & { extensionId }>`。

**效果**：数组每个元素保留自己的具体 `K`，`name` 与 `component` 的对应关系仍由同一个
`K` 约束（类型安全不丢）；编译后 JS 不变、运行时行为不变（`ExtensionSlot.tsx` 渲染时
本来就用 `getFrontendSlotRegistrations<K>(name)` 拿具体类型）。

### 7.6 待评审事项（留待后续决定）

- [ ] 是否采纳 `AnyFrontendSlotRegistration` 这个命名与「分布式联合」方案？
- [ ] 若后续新增第 4 种插槽，联合类型会自动扩展（mapped type 特性），无需手动维护；确认团队接受该约定。
- [ ] 替代方案（若不想改核心）：让二开组件显式 `as` 断言、或把 component 声明为
      `ComponentType<any>`——但会牺牲类型安全，不推荐。
- [ ] 回退方式：仅还原 `types.ts`、`registry.ts` 两处即可；`chanlun` 扩展需随之改回
      兼容写法（或暂不启用该插槽）。

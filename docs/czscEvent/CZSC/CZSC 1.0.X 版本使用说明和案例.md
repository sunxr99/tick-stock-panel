# CZSC 1\.0\.X 版本使用说明和案例

1\.0\.X 版本发布前，必须跑通当前文档下的所有案例，并配备完整的使用说明。

本页是 CZSC 1\.0\.X 全部案例的入口。先用下面的「快速速查表」按使用场景定位，再点对应案例进入详细文档。所有案例都已实际跑通，可在本地一行命令复现。

## 一、快速速查表（按场景找案例）

|序号|我想……|推荐案例|
|---|---|---|
|1|跑通端到端：从 Event/Position 配置到回测 \+ HTML 报告|[案例：基于 Event 的策略回测 \+ wbt HTML 报告](https://s0cqcxuy3p.feishu.cn/wiki/Li7ewsbReiQlWokEEVpcvLjznJU)|
|2|把缠论结构（分型 / 笔 / 线段 / 中枢）渲染成可分享的离线 HTML|[案例：lightweight\_charts 缠论可视化](https://s0cqcxuy3p.feishu.cn/wiki/VF7Gwq3N8iuplckG1Tmcmp1Qn3d)|
|3|把信号函数的触发点直接叠到 K 线主图上做观察 / 调参|[案例：把信号函数画到 K 线主图（plot\_czsc\_signals）](https://s0cqcxuy3p.feishu.cn/wiki/ULxhwFyVkiavqhkZ2Xkc0N3fnYc)|
|4|评估本地 CZSC / CzscTrader 的吞吐量，做容量规划|[性能基准测试：在本地复现 CZSC / CzscTrader 吞吐量](https://s0cqcxuy3p.feishu.cn/wiki/ReRfw9WUjiVgEckZbMxcT87WnRc)|
|5|系统了解 246 个信号函数的模块划分 / 参数模板 / 信号表达示例|[信号函数模块深入介绍](https://s0cqcxuy3p.feishu.cn/wiki/WxU8wKTBViekKbkCyKzcwa7SnJd)|
|6|用 Tushare 真实数据跑通 Event 策略回测 \+ HTML 报告|[案例：Tushare 真实数据跑 Event 策略回测](https://s0cqcxuy3p.feishu.cn/docx/Y3oZdUqKQo83yZxJAM7cyf3Pn3b)|
|7|理解复权 / 单利回测 / 策略衰减等量化研究基础问题|[量化研究基础知识](https://s0cqcxuy3p.feishu.cn/wiki/GDaWwIzqKi41IpkvHmAcowqOnMf)|
|8|用 Tushare 真实数据在多只股票截面跑缠论事件选股 \+ WeightBacktest HTML 报告|[案例：使用 Tushare 数据执行缠论事件选股](https://s0cqcxuy3p.feishu.cn/wiki/Dlzswr1eAivnzAk2yf4cz4TYnPd)|

## 二、案例详细介绍

### 案例 1 · 基于 Event 的策略回测 \+ wbt HTML 报告

**适合人群：**想跑通完整 Event → Position → 回测 → HTML 报告闭环的用户。

**能看到什么：**

- 5 行命令跑起来；Event / Position 如何配置；holds → wbt 权重表的关键代码段

- 关键指标卡片、累计净值曲线（单 Event vs 多 Event 对比）、月度收益热力图

- 可交互的 HTML 回测报告样例，含完整可运行脚本与后续扩展方向

[https://s0cqcxuy3p.feishu.cn/wiki/Li7ewsbReiQlWokEEVpcvLjznJU]()

### 案例 2 · lightweight\_charts 缠论可视化

**适合人群：**想把缠论分析结果离线分享、或嵌入 web 页面的用户。

**能看到什么：**

- PyPI 安装 → 几行代码生成自包含离线 HTML（双击即可在浏览器查看）

- HTML 端 4 类交互：多周期切换 tab、悬停 tooltip、light/dark 主题、图例 toggle

- Streamlit 在线版玩法；CZSC 单周期 / CzscTrader 多周期对象的 Python 调用与参数一览

[https://s0cqcxuy3p.feishu.cn/wiki/VF7Gwq3N8iuplckG1Tmcmp1Qn3d]()

### 案例 3 · 把信号函数画到 K 线主图（plot\_czsc\_signals）

**适合人群：**需要直观观察信号触发位置、调试 signals\_config 的用户。

**能看到什么：**

- 三分钟跑通；signals\_config 最小结构 \+ 多周期 / 多信号组合的写法

- marker 视觉规则（颜色语义、形状循环、图例 chip 颜色）与 transition 触发规则

- 典型场景：跨周期联立观察、tail\_bars 截窗、Streamlit 嵌入、不落盘 HTML 字符串输出

[https://s0cqcxuy3p.feishu.cn/wiki/ULxhwFyVkiavqhkZ2Xkc0N3fnYc]()

### 案例 4 · 性能基准测试：在本地复现 CZSC / CzscTrader 吞吐量

**适合人群：**需要评估本地性能、做容量规划、或核对 Rust 实现加速效果的用户。

**能看到什么：**

- 完整可运行脚本 \+ 一行命令复现；样例输出长什么样

- 关键指标速查表，以及「吞吐量是否达标」的三个常见判断

- 如何改测试规模 / 周期；影响吞吐量的因素清单

[https://s0cqcxuy3p.feishu.cn/wiki/ReRfw9WUjiVgEckZbMxcT87WnRc]()

### 案例 5 · 信号函数模块深入介绍

**适合人群：**想系统了解 czsc\-signals 架构、编写或扩展信号函数、按场景查询信号 / 参数模板的用户。

**能看到什么：**

- 主文档：模块全景 / 核心类型 / 参数体系 / `#[signal]` 宏注册 / 信号字符串 7 段协议 / Signal → Event → Position 链路 / 22 个 \.rs 文件分类速查 / Python 端到端示例 / 性能基线

- 2 张画板：架构总览（编译期 / 运行期 / 调用期三层）\+ 时序图（一根 K 线驱动一次开仓 / 平仓的全过程）

- **完整 246 信号词典附录**：按 \.rs 文件分组，每个信号含 template / 类别 / opcode / 信号逻辑 / **可直接复用的信号表达示例**（如 `60分钟_D1N30M20TH5_ADTMV230603_看多_任意_任意_0`）

- 配套脚本：`scripts/dump_signal_catalog.py`（速查表） \+ `scripts/dump_signal_details.py`（词典）一键重生成

[https://s0cqcxuy3p.feishu.cn/wiki/WxU8wKTBViekKbkCyKzcwa7SnJd]()

---

### 案例 6 · Tushare 真实数据跑 Event 策略回测

**适合人群：**想用真实 A 股 / ETF 数据跑通 Event 策略回测的用户。**能看到什么：**

- 如何用 `czsc.connectors.ts_connector` 接入 Tushare Pro 获取 30 分钟 K 线

- 与 mock 版本的区别（数据源、品种、复权处理）

- 完整可运行脚本：一键产出离线 HTML 回测报告

- 常见问题：Tushare 积分 / 频率限制 / 品种列表获取

[https://s0cqcxuy3p.feishu.cn/docx/Y3oZdUqKQo83yZxJAM7cyf3Pn3b]()

---

### 案例 7 · 量化研究基础知识

**适合人群：**研发新策略 / 跑回测前，想先把基础口径问题弄清楚的用户。**能看到什么：**

- **复权基础知识**：股票后复权 vs 前复权、期货主力换月差值法 vs 比例法

- **为什么策略回测要用单利**：复利幻觉 vs 单利公平比较，wbt 的 cumsum 口径

- **策略收益能力衰减**：赢家偏差 / 策略被市场嗅到 / 交易本身改变市场

[https://s0cqcxuy3p.feishu.cn/wiki/GDaWwIzqKi41IpkvHmAcowqOnMf]()

---

### 案例 8 · 使用 Tushare 数据执行缠论事件选股

**适合人群：**想把缠论"三买"等事件铺到多只股票截面、用真实 A 股日线 \+ WeightBacktest 出 HTML 报告的用户。

**能看到什么：**

- 端到端 6 步流程：Tushare 多 symbol 日线 → 缠论信号 → Event 打 0/1 → `adjust_holding_weights` 扩展持仓 → `WeightBacktest` → 自包含 HTML 报告

- 完整可运行脚本（`docs/examples/18_tushare_daily_event_universe.py`），默认 50 只股票 \+ 2020–2024 后复权日线，约 30 秒跑完，产物为 `report.html` \+ `stats.csv`

- 改造旋钮：换股票池 / 多事件 OR / 加趋势风控过滤（AND） / 信号平仓（切换到 `Position`） / 截面多空对冲 / 切换基础周期，每个都给了代码模板

- 与案例 1、6 的差异：那两个是**单只标的 \+ 30 分钟** \+ `CzscStrategyBase.backtest`；本案例是**多只股票 \+ 日线** \+ 截面权重矩阵 \+ `adjust_holding_weights` \+ `WeightBacktest`，两条链路互补

[https://s0cqcxuy3p.feishu.cn/wiki/Dlzswr1eAivnzAk2yf4cz4TYnPd]()

> （注：部分内容可能由 AI 生成）

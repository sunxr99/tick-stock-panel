# AI Context 索引

本目录只存放稳定、需跨任务复用的知识；符号位置、引用关系和实时实现细节请在任务中用 Serena 查询。

| 文档 | 包含什么 | 何时读取 | 对应源码模块/目录 |
| --- | --- | --- | --- |
| [architecture.md](architecture.md) | 分层、核心入口、主数据流与高冲突接线点 | 需要判断改动应落在哪一层，或涉及前后端链路 | `backend/app/main.py`、`api/`、`services/`、`tickflow/`、`frontend/src/` |
| [data-contracts.md](data-contracts.md) | 数据 Provider 边界、存储与 enriched、不可混用的金融数据口径 | 数据源、行情、K 线、指标、缓存或 API 字段相关任务 | `backend/app/data_providers/`、`tickflow/`、`indicators/`、`parquet.py` |
| [domain-flows.md](domain-flows.md) | 日常流水线、策略/监控、回测的职责边界和检索起点 | 修改或排查指标、策略、监控、回测、挖掘功能 | `jobs/`、`indicators/`、`strategy/`、`backtest/`、相关 API/测试 |
| [extensions.md](extensions.md) | 已实现扩展机制、开放插槽和二开检索原则 | 新页面、定制数据源、通知扩展或评估升级兼容时 | `backend/app/extensions/`、`frontend/src/extensions/`、`*/custom/`、`plugins/` |
| [development-workflow.md](development-workflow.md) | 最小变更、验证、缓存一致性与前后端协作约定 | 所有实现、调试与代码审查任务；不替代完整贡献规范 | `CONTRIBUTING.md`、`backend/tests/`、`frontend/src/lib/`、前后端写路径 |

使用顺序：先读根目录 `AGENTS.md` 与 `CONTRIBUTING.md`，优先查询 Understand Anything 已有索引，再按本表选择最少的文档；随后用 Serena 定位符号和关系，最后才读必要源码。不得为“理解项目”重复进行全量扫描或全量源码读取。

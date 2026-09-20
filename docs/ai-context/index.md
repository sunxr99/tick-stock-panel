# AI Context 索引

本目录只存放稳定、需跨任务复用的知识；符号位置、引用关系和实时实现细节请在任务中用 Serena 查询。

| 文档 | 包含什么 | 何时读取 | 对应源码模块/目录 |
| --- | --- | --- | --- |
| [architecture.md](architecture.md) | 分层、核心入口、主数据流与高冲突接线点 | 需要判断改动应落在哪一层，或涉及前后端链路 | `backend/app/main.py`、`api/`、`services/`、`tickflow/`、`frontend/src/` |
| [data-contracts.md](data-contracts.md) | 数据 Provider 边界、存储与 enriched、不可混用的金融数据口径 | 数据源、行情、K 线、指标、缓存或 API 字段相关任务 | `backend/app/data_providers/`、`tickflow/`、`indicators/`、`parquet.py` |
| [domain-flows.md](domain-flows.md) | 日常流水线、策略/监控、回测的职责边界和检索起点 | 修改或排查指标、策略、监控、回测、挖掘功能 | `jobs/`、`indicators/`、`strategy/`、`backtest/`、相关 API/测试 |
| [extensions.md](extensions.md) | 已实现扩展机制、开放插槽和二开检索原则 | 新页面、定制数据源、通知扩展或评估升级兼容时 | `backend/app/extensions/`、`frontend/src/extensions/`、`*/custom/`、`plugins/` |
| [development-workflow.md](development-workflow.md) | 最小变更、验证、缓存一致性与前后端协作约定 | 所有实现、调试与代码审查任务；不替代完整贡献规范 | `CONTRIBUTING.md`、`backend/tests/`、`frontend/src/lib/`、前后端写路径 |
| [Sector Strength 与 Relative Strength V1](../theory/sector-rs/sector-strength-relative-strength-v1.md) | 冻结的板块强度与个股 RS 口径、DTO、只读查询接口和已知边界 | 修改板块 / 个股相对强弱、候选池前置研究或历史验证时 | `services/rps_rotation.py`、`services/relative_strength.py`、`api/rps.py` |
| [候选池链路审阅复核（2026-09-13）](../audits/candidate-pool-chain-audit-review-2026-09-13.md) | Wyckoff、Sector/RS、VP 的职责、现行研究字段隔离、审阅中已过时结论与证据层决策 | 调整候选排序、解释 Strategy score，或审查 VP/Sector/RS 接线时 | `strategy/engine.py`、`services/wyckoff_candidate_ranking.py`、`services/volume_profile.py` |
| [Volume Profile 参考源码学习与接入设计](../theory/volume-profile/volume-profile-reference-study.md) | 指定参考库的 VAP/POC/VA/HVN-LVN 算法、非重绘约束、当前 OHLCV 能力与内部 Engine 设计 | 设计或实现 VP、VP20/60、WyckoffRangeVP、位置/接受/延展上下文时 | `reference/py-market-profile-master/`、`tickflow/repository.py`、`data_providers/` |
| [Volume Profile V1（分钟实现）](../implementation/volume-profile/volume-profile-v1-minute-implementation.md) | 分钟 Range Overlap 的正式 V1、数据质量、DTO、fallback、测试、性能和已知边界 | 使用、验证或扩展当前 VP20/VP60/Range VP 时 | `services/volume_profile.py`、`tickflow/repository.py`、`scripts/run_volume_profile_research.py` |
| [Volume Profile Extension 修复与五日回填](../research/volume-profile/volume-profile-extension-fix-random5.md) | Extension 调用顺序修复、共享纯分类函数、既有五日 VP 标签的无分钟重算回填及研究边界 | 修复、复用或审计 VP Extension 时 | `services/volume_profile.py`、`tests/test_volume_profile.py`、`scripts/derive_vp_extension_random5.py` |
| [Volume Profile V1（批量性能）](../implementation/volume-profile/volume-profile-v1-batch-performance.md) | 运行级 BatchMinuteDataContext、Lite/Full 编排、IO/内存边界、结果一致性与性能基准 | 优化候选池 VP 执行、选择批大小或评估 Full 计算成本时 | `services/volume_profile.py`、`tickflow/repository.py`、`scripts/benchmark_volume_profile_batch.py` |

使用顺序：先读根目录 `AGENTS.md` 与 `CONTRIBUTING.md`，优先查询 Understand Anything 已有索引，再按本表选择最少的文档；随后用 Serena 定位符号和关系，最后才读必要源码。不得为“理解项目”重复进行全量扫描或全量源码读取。

# 核心领域流程

## 日常数据与 enriched

`backend/app/jobs/daily_pipeline.py` 编排日常数据流程；指标流水线入口为 `backend/app/indicators/pipeline.py` 的 `run_pipeline`。它也被历史扩展和 K 线重建任务调用。指标层优先向量化计算，输出 enriched 数据供后续业务复用。

涉及数据或指标变更时，按顺序追踪：Provider/标准化 → 仓库/Parquet → enriched → 消费服务/API → 前端缓存键与页面；只读取当前改动链上的符号和测试。

## 策略与监控

`backend/app/strategy/engine.py` 的 `StrategyEngine` 统一加载、校验、参数解析、执行、组合策略和实时矩阵准备。策略、监控与回测应共享已定义的数据和结果契约，不各自创造指标口径。

监控依赖标准化实时行情和统一规则；热路径不得同步执行全量历史重算、慢磁盘扫描或 Webhook。改动策略参数时需检查持久化、运行时实例、策略结果缓存、监控和前端查询。

## 回测与研究

`backend/app/backtest/engine.py` 的 `BacktestEngine` 提供数据面板加载、缓存、独立候选与组合模拟、分钟成交处理及统计。API 与回测服务/worker 负责调用它。

必须分离信号生成与成交模拟，明确可用时间与成交价格，防止未来函数；股票规则还需保留 T+1、费用、滑点、涨跌停不可成交等约束。面板或矩阵缓存改动须确认 key、失效和 generation 一致性。

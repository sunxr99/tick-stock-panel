# Volume Profile V1: 批量读取与运行级缓存性能改造

日期：2026-09-12

## 结论

本次只改变分钟数据读取、运行级内存复用与批量编排；没有改变 `MINUTE_RANGE_OVERLAP`、100 个价格桶、POC、70% Value Area、HVN/LVN、VP20/VP60/RangeVP、动态状态或任何正式排序规则。

在 2026-02-27 的 `ALL_WYCKOFF` 真实候选中，500 个候选的 `VP_LITE`：

| 候选数 | 旧单股票 VP20 | Batch VP_LITE | 加速比 |
| ---: | ---: | ---: | ---: |
| 20 | 8.08 s | 1.82 s | 4.43x |
| 100 | 28.14 s | 5.45 s | 5.16x |
| 500 | 137.61 s | 19.38 s | 7.10x |

100 个候选的 `VP_FULL`（VP20、VP60、as-of 安全 RangeVP、D/D-1/D-3 动态上下文）为 49.05 s。没有把 VP 接进正式评分或 `final_rank_score`。

## 修改文件

- `backend/app/tickflow/repository.py`
  - 新增 `get_minute_by_dates_and_symbols(dates, symbols)`。一个日期分区只由一次批量查询读取，随后一次性过滤候选 symbol。
- `backend/app/services/volume_profile.py`
  - 新增 `BatchMinuteDataContext`、`VolumeProfileMode`。
  - 新增 `prepare_batch_context`、`build_from_context`、`build_with_dynamic_context_from_context`、`build_batch`。
- `backend/scripts/run_volume_profile_context_validation.py`
  - 改为复用正式 `BatchMinuteDataContext`，不再自行实现临时缓存仓库。
- `backend/scripts/benchmark_volume_profile_batch.py`
  - 可复现 20/100/500 的旧/新性能及内存基准。
- `backend/tests/test_volume_profile.py`
  - 增加批量路径与单股票路径结果一致性、Lite/Full、批量 Repository API 回归。

## 原始瓶颈与 Profiling

旧路径中，每个候选的 VP20 独立调用 `get_minute_by_dates(symbol, 20 dates)`。因此 500 个候选约触发 10,000 个日期分区扫描；VP60、RangeVP 与 D/D-1/D-3 又会放大重复读取。

Polars 在一次 lazy query 中融合 Parquet 分区读取、decode 与 `symbol.is_in(...)` predicate；因此无法在不故意做两次 scan 的情况下，把物理读取、decode 和 symbol filter 分成三个互斥精确时间。本报告将它们诚实记录为 `minute_partition_read_and_filter_ms`，而非虚构独立数字。

| 候选数 | minute partition read/filter | VP20 compute | 总计（Lite） | 分区读取数 |
| ---: | ---: | ---: | ---: | ---: |
| 20 | 1.05 s | 0.55 s | 1.82 s | 94 |
| 100 | 1.96 s | 3.20 s | 5.45 s | 94 |
| 500 | 3.15 s | 15.76 s | 19.38 s | 96 |

`daily_batch_read_ms` 分别为 0.22 s、0.29 s、0.46 s，已包含在 prepare 时间中。`VP_FULL` 的 100 候选耗时拆分为：prepare 2.25 s，Full 动态 Profile 计算 46.80 s，总计 49.05 s。由此可见：

1. 优化前主要瓶颈是重复分钟 IO；
2. 批量读取后，Lite 的主要成本变为纯 histogram 计算；
3. Full 的主要成本是正确但较重的 VP20/VP60/RangeVP 的 D/D-1/D-3 重算，而不是磁盘 IO。

## BatchMinuteDataContext

一次批量任务生命周期如下：

```text
Wyckoff candidate batch + as_of
  -> get_daily_batch（一次）
  -> 推导 VP60 D/D-1/D-3 及 Range 所需交易日
  -> 每个日期分区读取一次并筛选本批候选
  -> (symbol, date) -> minute DataFrame
  -> VP20 / VP60 / RangeVP / dynamic 在内存切片
  -> 任务结束释放 context
```

`BatchMinuteDataContext` 保存：

- `daily_by_symbol`
- `minute_by_symbol_date`
- 已请求分钟交易日、分区读取数、行数、DataFrame 估算字节数
- `daily_batch_read_ms`、`minute_partition_read_and_filter_ms`、prepare 总耗时

RangeVP 的确认元数据也已收口到服务契约：`VolumeProfileRequest` 同时携带 `range_start` 与 `range_confirmed_at`。`WYCKOFF_RANGE` 在确认日缺失或晚于 `as_of` 时返回 `UNAVAILABLE`；`prepare_batch_context` 会在推导预载日期前过滤这类 Range。因而调用方遗漏检查也不会把未来确认的结构回填到历史，且不会为它额外加载分钟数据。

它仅持有不晚于 `as_of` 的日期。即使调用方的底层仓库随后出现未来数据，context 也不会拥有它；`get_minute_by_dates` 仍显式过滤 `date <= as_of`。

## Lite 与 Full

`VP_LITE` 面向整个 Wyckoff 候选池，只计算：

- VP20
- POC / VAH / VAL
- Position
- 静态 upside extension

不计算 VP60、RangeVP、D/D-1/D-3 迁移、Acceptance、HVN/LVN 的额外 Full 研究输出。

`VP_FULL` 面向较小候选集，保持原 V1 计算语义：

- VP20、VP60、as-of 安全 WyckoffRangeVP
- POC / Value Area migration
- Acceptance、完整 Extension、HVN/LVN

这些模式只控制执行范围，不改变任何已执行 Profile 的数学结果。未来可支持 `ALL_WYCKOFF -> VP_LITE -> 研究阶段较小集合 -> VP_FULL`，但本轮没有把候选数量写成正式策略参数。

## 一致性与 Non-Repainting

新增回归比较同一 symbol/date 的旧单股票路径与预加载路径：

- histogram bins
- POC / VAH / VAL
- Position / Acceptance / Extension
- POC / Value Area dynamic state

结果一致（浮点比较使用合理容差）。真实数据抽查 `000001.SZ`、2026-02-27 的 POC、VAH、VAL、Acceptance、POC State 完全一致。

批量 context 只从 `as_of` 当日和此前日线推导所需分钟日期；已有 Future Bar Isolation 与 Prefix Consistency 测试继续适用，并新增 batch context 的 `requested_minute_dates <= as_of` 回归。

## 内存控制

500 候选、96 个分钟分区：

- 载入分钟行：8,293,292
- context DataFrame 估算：514.09 MB
- 实测 Python RSS：基线 155.46 MB，prepare 后峰值约 1,634.87 MB，Lite 后约 1,608.70 MB

因此单次 500 候选虽然可运行，但不应作为默认内存预算。建议运行编排按约 100–200 symbols 分批加载；这仍然是批量日期分区读取，不会退回逐股票磁盘 IO。批大小是工程内存控制，不是策略或收益参数。

## 可复现实测

```powershell
cd backend
uv run --frozen python scripts/benchmark_volume_profile_batch.py
```

产物：`data/research/volume_profile_batch_benchmark.json`。

## 回答

1. 当前最主要瓶颈是 IO 还是 VP 计算？
   - 优化前：重复分钟 IO；优化后 Lite 主要是 histogram 计算，Full 主要是多窗口动态 Profile 计算。
2. 批量读取后，同一日期分钟分区是否只读取一次/少量次数？
   - 是。在一个 batch context 内，同一请求日期只读取一次；500 候选为 96 次分区读取，而非数千次。
3. VP20/VP60/D/D-1/D-3 是否共用分钟数据？
   - 是。它们全部从同一 run-scoped context 的 `(symbol, date)` bars 切片，不再访问磁盘。
4. 500 只候选提升多少？
   - VP_LITE 为 137.61 s -> 19.38 s，7.10x。
5. VP_LITE 是否可覆盖全部 Wyckoff 候选？
   - 技术上可以；应以 100–200 symbols 的内存分批编排。
6. VP_FULL 对较小候选池是否具备实用性能？
   - 100 候选约 49.05 s，适合作为第二阶段研究/复核，不应未经进一步 CPU 优化就对数百候选同步执行。
7. 是否仍需 V2 fixed grid、daily histogram、rolling add/remove、并发？
   - 当前不需要为 Lite 引入它们。若未来要求数百候选的 Full 在更短时间完成，优先研究纯计算优化和内存分批；固定 grid / rolling histogram 需要独立 V2 研究，不能直接引入。线程/进程并发不是第一选择，因为当前先要避免内存与磁盘竞争。

## 当前限制

- Parquet 的 date partition 内仍包含全市场数据；批量 API 消除了同一运行内的重复 scan，但不会改变文件物理布局。
- Full 的动态 Profile 重建是有意保留的 V1 精确语义；本轮不做不可安全相加的 daily histogram cache。
- 本轮不创建 VPScore，不修改 Wyckoff、Sector、RS、CZSC 或 `final_rank_score`。

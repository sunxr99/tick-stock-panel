# Volume Profile Engine V1（分钟 OHLCV）

## 结论

V1 新增了一个**只读、未接入正式候选排序**的 Volume Profile 计算层。默认请求是
`MINUTE_RANGE_OVERLAP`：以 1 分钟 OHLCV 的 High--Low 与价格桶重叠比例分配成交量。
日线只在分钟覆盖不足时以显式 `FALLBACK` 返回；`CLOSE_ONLY` 仅保留为参考实现对照。

本实现不把一分钟 OHLCV 伪装成逐笔成交 Volume Profile：它是对每一分钟价格区间内
成交的均匀分布近似。

## 文件与边界

| 文件 | 职责 |
| --- | --- |
| `backend/app/services/volume_profile.py` | 纯 `VolumeProfileEngine`、共享 `RangeOverlapAllocator`、DTO 与仓库适配 `VolumeProfileService` |
| `backend/app/tickflow/repository.py` | 修复 `get_minute_by_dates()` 的 Windows 分区路径读取，使本地分钟数据能够被 VP 和现有分钟回测准确读取 |
| `backend/tests/test_volume_profile.py` | 算法、质量、fallback、范围、未来数据和 Windows 分区回归测试 |
| `backend/scripts/run_volume_profile_research.py` | 只读的真实数据抽样、三模式比较和性能复现实验入口 |

没有修改 Wyckoff、Sector Strength、Relative Strength、NARROWING、CZSC 或
`final_rank_score`。本轮没有 VP Score，也没有把 VP 写入候选排序。

## 输入、模式与数据质量

`VolumeProfileService` 通过既有 `KlineRepository` 读取：

```text
MINUTE_RANGE_OVERLAP -> get_minute_by_dates(symbol, trading_dates)
DAILY_RANGE_OVERLAP  -> get_daily(symbol, start, as_of)
CLOSE_ONLY           -> 分钟优先；不足时显式日线 fallback
```

结果 `VolumeProfileResult` 固定记录：`data_granularity`、`allocation_mode`、
`expected_minute_bars`、`actual_minute_bars`、`minute_coverage_ratio`、`quality`、
`fallback_used` 与 `unavailable_reason`。因此分钟不足时绝不会静默混进日线并继续
标成分钟 VP。

分钟质量按目标股票本身的日线活跃日生成预期日期；日线 `volume=0` 的停牌日不被
错误计为缺分钟。每个窗口检查重复/倒序 timestamp、缺活跃交易日、OHLC/volume 异常、
大量零成交量、非预期的盘中缺口（5--60 分钟）和交易日错误。每个有效日以窗口中观测
到的最大有效分钟根数作为 session 基准，而不是硬编码 240 根。

```text
coverage >= 98%         FULL
90% <= coverage < 98%   PARTIAL
coverage < 90%          INSUFFICIENT -> 可选 DAILY fallback
```

## Range Overlap、价格桶与 Volume Conservation

默认 `bin_count=100`，区间为 `min(low)` 到 `max(high)`，每桶等宽。对一根 bar：

```text
overlap(i) = max(0, min(bar_high, bin_high[i]) - max(bar_low, bin_low[i]))
allocation(i) = bar_volume * overlap(i) / (bar_high - bar_low)
```

当 `high == low` 时，整根成交量进入该价格所在桶；当 profile 本身只有单一价格时
使用一个退化桶，避免除零和伪造 100 个相同价格桶。分配尾差确定性地补到 close 所在桶，
所以 `sum(bin.volume)` 与输入有效 bar 的 `sum(volume)` 在浮点误差范围内守恒。

`DAILY_RANGE_OVERLAP` 完全复用同一个分配器，只是输入改成日线。`CLOSE_ONLY`
把整根 K 的量放入 close 桶，用于复现参考库的 baseline，不作为正式默认模式。

## POC、Value Area、HVN/LVN

- **POC**：最大 volume 的价格桶；并列时先取离 profile 中点最近的桶，仍并列取较低
  bin；价格为 bin center。
- **Value Area**：从 POC 开始累计，比较左右相邻桶并加入成交量更大的一侧；相等时取
  高价侧，直至累计至少为总量的 70%。`VAL` 是最低入选桶下边界，`VAH` 是最高入选桶上边界。
- **HVN/LVN**：仅输出严格局部高/低量节点，不平滑、不做 prominence、不参与评分。

## VP20、VP60 与 WyckoffRangeVP

- **VP20/VP60**：先从个股日线中选取截至 `as_of` 最近 20/60 个实际存在的交易日，再
  读取这些日期的分钟 bar。少于所需日数时返回 `UNAVAILABLE`，不会把较短窗口称为 VP20/60。
- **预热**：例如在 2025-10-31，历史分钟数据从 2025-09-12 起，VP20 可完整生成；VP60
  只能获得 50% 分钟覆盖，按默认策略明确输出日线 `FALLBACK`。
- **WyckoffRangeVP**：只接受调用方传入的**正式 Wyckoff Trading Range start**；当前
  `TradingRange` DTO 没有 start 字段，因此传入缺失时返回
  `wyckoff_range_start_unavailable`，绝不自行从价格重新猜 range。若 start 早于分钟历史
  但仍有后段分钟数据，返回 `MINUTE_1M + PARTIAL`，并保留 `requested_start/data_start`。

## 动态、位置、接受与延展上下文

针对同一 profile，`build_with_dynamic_context()` 以当前日、前 1 个和前 3 个交易日分别
重新构建 profile，输出 `poc/vah/val_change_1d_pct` 与 `*_change_3d_pct`。它不复用未来
区间的最终 profile。

固定、非收益优化的描述阈值是 3 日变化 `+/-0.5%`：

```text
POC_RISING / POC_FLAT / POC_FALLING
VALUE_AREA_RISING / VALUE_AREA_STABLE / VALUE_AREA_FALLING
```

位置字段为 `BELOW_VAL`、`WITHIN_VALUE`、`ABOVE_VAH`，并独立标出价格距 POC/VAH/VAL
不超过 0.5% 的 `NEAR_*`。只有当价格在 VAH 之上、POC 3 日上移且 VAH/VAL 同时 3 日上移，
才是 `ABOVE_VAH_ACCEPTED`；其余 VAH 上方情况为 `ABOVE_VAH_UNACCEPTED`。

延展不是买卖信号。若价格没有高于 VAH，状态为 `VP_NORMAL`；高于 VAH 时优先用日线
ATR14 归一化距 VAH 的距离：`<=1 / <=2 / <=3 / >3 ATR` 对应
`NORMAL/ELEVATED/EXTENDED/EXTREME`。ATR 不可用时固定使用 `2%/5%/8%` 的距离门槛。

`with_context()` 必须先写入 `position_context`，再计算 Extension；`_extension_state()`
依赖 `ABOVE_VAH` 的位置语义。Extension 分类已通过公开的纯方法
`VolumeProfileEngine.extension_state_for()` 复用，因此可以只依据已落盘的 Position、
distance-to-VAH 和 ATR distance 回填研究标签，而无需重建分钟 Histogram。2026-02 的
五日研究旧文件曾因调用顺序错误将 Extension 都写为 `VP_NORMAL`；原始文件保持不变，
修复版标签见 `docs/research/volume-profile/volume-profile-extension-fix-random5.md` 及对应 research Parquet。

`VolumeProfileResearchContext` 可持有 `sector_phase`、`narrowing_flag`、`rs_state` 与
`vp20/vp60/wyckoff_range_vp` 三个独立结果；它只是未来只读研究连接 DTO，不参与排序。

## Non-Repainting

`VolumeProfileEngine.build_profile()` 再次截断传入 bar：date 型 `as_of=D` 可使用 D 的完整
收盘会话；datetime 型 `as_of` 严格使用 `bar.datetime <= as_of`。即使调用者错误混入 D+1
或同日更晚分钟数据，也不能改变当前 histogram、POC、VAH、VAL、节点或位置。动态结果按
历史 `as_of` 重算而非从当前完整窗口回推。单元测试覆盖 Future Bar Isolation、同日未来
minute isolation 与 Prefix Consistency。

## 单元测试与真实样本

定向测试：

```text
uv run --frozen pytest tests/test_volume_profile.py tests/test_minute_range_api.py -q -p no:cacheprovider
33 passed
```

覆盖分钟/日线 volume conservation、Close-only、POC、并列 POC、Value Area、退化价格、
零量、桶边界、空数据、VP20/60 预热、分钟不足 fallback、Range start 缺失、Range 分钟历史
截断、future isolation、prefix consistency、三模式生成、接受状态和 Windows 分区读取。

真实抽样（`000001.SZ`、`600519.SH`、`300750.SZ`）：

| as_of | Profile | 分钟质量 | 观察 |
| --- | --- | --- | --- |
| 2025-10-31 | VP20 | FULL，4,820/4,820 | 三只股票都使用正式分钟分布；宁德时代 minute POC 391.80，daily POC 361.10 |
| 2025-10-31 | VP60 | DAILY FALLBACK，7,230/14,460 | 一年分钟历史的预热边界生效，未伪装成完整 VP60 |
| 2026-02-27 | VP20 | FULL，4,820/4,820 | 三只样本均为分钟正式输出 |
| 2026-02-27 | VP60 | FULL，14,460/14,460 | 三只样本均为分钟正式输出 |

2026-02-27 的 VP20 POC 差异（minute vs daily vs close-only）：

| symbol | Minute range | Daily range | Close-only（分钟） |
| --- | ---:| ---:| ---:|
| 000001.SZ | 10.5876 | 10.6713 | 10.6108 |
| 600519.SH | 1311.8762 | 1314.2793 | 1311.8762 |
| 300750.SZ | 337.2467 | 337.6866 | 337.2467 |

差异会随股票和窗口改变：2025-10-31 的 300750.SZ 分钟 POC 比日线 POC 高约 8.5%。因此
研究与后续候选上下文必须保留 `data_granularity/allocation_mode`，不能把三种算法混合比较。
完整 histogram 位于 DTO 的 `bins`（每桶 `index/low/high/center/volume`）；可通过下列只读
脚本复现样本：

```powershell
cd backend
uv run --frozen python scripts/run_volume_profile_research.py
```

## 性能

在本机、2026-02-27、VP20、使用现有按单 symbol 读取的 V1 路径：

| candidates | elapsed | 每只 | FULL / PARTIAL / FALLBACK / UNAVAILABLE |
| ---: | ---: | ---: | --- |
| 20 | 5,446ms | 272ms | 19 / 0 / 0 / 1 |
| 100 | 30,406ms | 304ms | 97 / 0 / 0 / 3 |
| 500 | 134,458ms | 269ms | 490 / 3 / 0 / 7 |

因此候选池级 20 只的只读研究可以直接使用 V1；500 只约 2.2 分钟，若未来要在每次
全市场策略运行中同步计算，需要在下一性能阶段引入**批量分钟读取或 profile cache**。
V1 没有提前实现增量 histogram。

## 当前限制与下一步

1. 分钟覆盖仅从 2025-09-12 起。早期 VP60 或早于此日期的 Range VP 会保持 PARTIAL、
   FALLBACK 或 UNAVAILABLE，取决于调用策略。
2. 没有逐笔成交或完整 depth5；分钟区间均分只是 VAP 近似。
3. 当前 Wyckoff 正式结构没有 range start，因而 `WyckoffRangeVP` 尚不能由正式漏斗自动生成。
4. 没有 API/前端 overlay，且没有任何正式 VP 排序或交易规则。

### 最终回答

1. **MINUTE_RANGE_OVERLAP 可以作为默认 VP 数据源**：在覆盖完整的 VP20/60 窗口中已经
   实测 `FULL`，且数据精度会显式记录。
2. **VP20 稳定生成；VP60 在预热后稳定生成**。WyckoffRangeVP 的计算器已实现，但必须由
   正式 Wyckoff 提供 range start；当前接口缺少这个字段，故暂时 fail-closed。
3. **是**：Engine 级 future filtering 与 prefix consistency 测试确认没有未来 bar 污染。
4. 一年分钟数据在 2025-09-12 后可用；2025-10 的 VP60 仍处于预热，2026-02 的 VP20/60
   样本为完整分钟覆盖。
5. 分钟历史前的窗口、分钟覆盖低于 90%、新股日线不足、或 Range start 缺失，分别明确
   fallback 或 unavailable，不静默降级。
6. 分钟、日线与 Close-only 已观察到显著 POC/VA 差异，特别是 300750.SZ 的 2025-10 VP20；
   因此分钟正式输出不能由日线/close-only 替代。
7. **尚不具备进入“Wyckoff候选 + Sector/RS + VP只读回测”的全部条件**：先需要在不改 Wyckoff
   判断规则的前提下，使正式输出提供 as-of 的 Trading Range start，并完成 100/500 只候选批量
   性能测量；之后才可以做只读 cohort 对照。

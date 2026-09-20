# Volume Profile 参考源码学习与接入设计

## 结论与边界

本研究只读取了 `reference/py-market-profile-master`，参考目录保持只读；没有修改 Wyckoff、Sector Strength、RS、NARROWING、CZSC 或 `final_rank_score`。

推荐未来采用**方案 C：在项目内部实现独立、纯计算的 `VolumeProfileEngine`**。参考项目的 Value Area 与 POC 的确定性思想可以借鉴，但不能直接依赖或照搬：其 Volume-at-Price（VAP）将一根 K 线的全部成交量放到 Close 所在桶，且不提供 as-of 防重绘、增量窗口、数据质量或项目现有 Provider/Parquet 契约。

本项目已经有一个不同概念的“筹码分布”实现：[`backend/app/indicators/levels.py`](../backend/app/indicators/levels.py) 的 `_support_resistance()` 以换手率衰减历史筹码，并把日成交量平均分到当日 high~low 覆盖桶。这是“当前持仓成本”近似，不是无衰减的海外 Volume Profile；未来 VP 不应与其混用、替换或叠加成同一个指标。

## 1. 指定参考源码的核心结构

| 分类 | 关键文件 / 方法 | 实际职责 |
| --- | --- | --- |
| 算法入口 | `src/market_profile/__init__.py`：`MarketProfile` | 保存 DataFrame、价格行参数及 `__getitem__` 的时间切片入口 |
| 算法核心 | 同文件：`MarketProfileSlice.build_profile()` | 构建按价格聚合的 profile，计算 POC、Value Area、HVN/LVN |
| Value Area | 同文件：`calculate_value_area()` | 从 POC 向相邻价格行扩展至目标成交量 |
| POC tie-break | `src/market_profile/utils.py`：`midmax_idx()` | 多个最高量桶时选择最接近 profile 中点的桶 |
| 辅助市场轮廓 | `MarketProfileSlice.open_range()`、`initial_balance()`、`calculate_balanced_target()` | 开盘区间、初始平衡、平衡目标；不是 VP 主算法必要输入 |
| 测试 | `tests/market_profile_test.py`、`tests/utils_test.py` | 固定样本的行价格、POC、VA、HVN/LVN 与 tie-break 测试 |
| UI / 展示 | `examples/example.ipynb` | 示例图表，不属于核心算法 |
| 文档 / 数据示例 | `README.rst`、`tests/fixtures/google.csv` | API 用法与 OHLCV 样例，不是数据适配层 |

参考库没有独立的数据 Provider、图表运行时或持久化层；调用方直接传入索引为时间戳、列名为 `Open/High/Low/Close/Volume` 的 pandas DataFrame。

## 2. 真正的 Volume-at-Price 算法

参考实现属于**方式 1：每根 K 的全部 Volume 放到其 Close 所在价格桶**，不是 Typical Price、high~low 分摊、重叠比例分摊，也不是 lower-timeframe/intrabar 逐笔聚合。

源码证据位于 `MarketProfileSlice.build_profile()`：

```python
rounded_set = self.ds['Close'].apply(lambda x: self.mp.round_to_row(x))
self.profile = self.ds.groupby(rounded_set)['Volume'].sum()
```

因此每根 K 的 `High`、`Low`、`Open` 不参与 VAP 分配；它们只在 `open_range()`、`initial_balance()` 中参与求区间。`mode='tpo'` 时同一代码路径只把每个 Close 计数一次：`groupby(... )['Close'].count()`，并非成交量 Profile。

这是一种计算很快但较粗的 Close-at-Price 近似：振幅大、日内来回成交多的 K 线也只贡献到收盘价。不能把它误述为真实的“成交发生价格”。

### 对当前项目的借鉴与改进

未来项目内 VP V1（仅日线）应使用**方式 4 的均匀重叠近似**，但要明确它仍是估计：

1. 将单根 K 的 `[low, high]` 与每个价格桶求交叠长度；
2. 当 `high > low` 时，把成交量按交叠长度比例分配，保证所有桶的分配和严格等于该 K 的 `volume`；
3. 当 `high == low` 时，将全部量归入包含 `close` 的桶；
4. 只要有完整 1 分钟 K，则对每根 1 分钟 K 重复同一算法，以更细时间粒度近似；仍不把 1 分钟 OHLCV 称为逐笔 VAP；
5. 将来有逐笔成交（price, size, timestamp）时，才改为按实际成交价精确聚合。五档盘口快照不能替代逐笔成交。

日线模式不能知道盘中真实成交密度；`amount` 只能用于数据一致性检查（例如价格与成交额/成交量是否异常），不应被伪装成逐价成交量。

## 3. 价格桶（bin / row）

### 参考实现

`MarketProfile.__init__()` 的参数为：

```text
tick_size = 0.05
prices_per_row = 1
row_size = tick_size * prices_per_row
```

`round_to_row(x)` 使用 `ceil(x / row_size) * row_size`。因此桶标签是**向上取整后的价格行**，可视为行的上边界，并非 bin center。实际 profile 的 high/low 是被占用桶标签的最小/最大 Close 行，不是输入 K 的最高/最低价；没有“bin 数量”参数，也不按 profile range 自动选择桶宽。

边界上，恰好等于行价格的值留在该行；介于两行之间的 Close 进入较高价格行。实现以 Python float 运算，没有十进制价格精度保护。

### 当前项目建议

不宜直接沿用默认 `0.05`：A 股不同资产的最小报价单位并不应在代码中假定。当前 instruments 标准字段没有 `tick_size`，故未来 Data Adapter 必须从可信的标的/交易所规则获得它；获取不到时以 `quality=PARTIAL` 明示降级，而不是静默硬编码。

建议采用统一、可解释的桶策略：

```text
profile_low  = min(valid low)
profile_high = max(valid high)
raw_width    = (profile_high - profile_low) / target_bin_count
bin_width    = ceil(raw_width / tick_size) * tick_size
bin_count    = ceil((profile_high - profile_low) / bin_width)
```

其中 `target_bin_count` 是显式请求参数（不是未来收益优化参数），`bin_width` 至少为一个 tick。输出保留 `profile_low`、`profile_high`、`bin_width`、`bin_count`、每个 bin 的 lower/upper/center/volume，以便前端与研究复核。左闭右开 `[lower, upper)`；最后一个桶右边界闭合；零振幅 K 用 close 所在桶，从而避免边界重复计量。

## 4. POC

参考实现的 POC 为**最大 Volume 的价格行**：

```python
self.poc_idx = midmax_idx(self.profile.values.tolist())
self.poc_volume = self.profile.iloc[self.poc_idx]
self.poc_price = self.profile.index[self.poc_idx]
```

多个最大桶时，`midmax_idx()` 选距离 `len(profile)/2` 最近者；这不是选离当前价最近者，也不是选最低/最高价。返回的是上述向上取整的桶标签（上边界），而非中心价。

参考库没有 Developing POC、POC 序列、增量更新或迁移趋势。若调用方在不同结束日期反复创建切片，可以外部观察 POC 变化，但库本身不保存历史 snapshot。

未来 `VolumeProfileResult.poc` 应明确采用**bin center**，同时可输出 `poc_bin_lower`、`poc_bin_upper` 和 `poc_volume`。并列最大值采用固定、测试覆盖的 tie-break（可借鉴“最接近 profile 中点，再取较低价格”）；不可按当前价格动态选取，否则同一 profile 的 POC 会随展示价格变化。

## 5. VAH / VAL 与 Value Area

参考实现的 `value_area_pct` 默认是 `0.70`。`calculate_value_area()` 的准确流程为：

1. `target_vol = total_volume * 0.70`；初始累计量为 POC 的成交量；
2. `min_idx = max_idx = poc_idx`；
3. 每轮取当前区间紧邻的下方行与上方行；
4. 比较两者成交量，加入较大的一侧；相等时加入上方行；仅一侧可用时加入可用侧；
5. 重复到累计量超过目标或两端均耗尽；
6. 返回 `[profile.index[min_idx], profile.index[max_idx]]`，即 VAL、VAH 的价格行标签。

它是“**从 POC 向两边的相邻桶逐步扩展**”，不是把全局最大 volume bins 排序后累计。实现循环条件为 `trial_vol <= target_vol`，因此当 POC 恰好等于目标时仍会多扩一行；每次加入整桶，最终总量通常高于 70%。

项目内可借鉴该相邻扩展语义，并在文档/测试固定以下细节：从 POC 开始，累计量小于目标时扩展；比较相邻两侧分配后的 volume；平局的方向固定；最终允许因整桶而超过目标。输出 `value_area_volume_ratio` 以核对实际覆盖比例，不能只报 VAH/VAL。

## 6. HVN / LVN

参考实现没有平滑、prominence、百分位阈值或 rolling window：

```python
(extrema_idx,) = argrelextrema(self.profile.values, sign)
```

`sign=np.greater` 返回严格局部极大（HVN），`sign=np.less` 返回严格局部极小（LVN）。SciPy 默认只比较相邻一格，端点不算极值；相等的平台通常不会成为严格极值。结果是完整 pandas Series，不做筛选或排序。

未来 V1 可先沿用这个简单且可解释的定义，返回所有严格局部节点，另带 `hvn_levels`/`lvn_levels` 的 bin 区间与 volume；前端可自行限制展示数量。不要在第一版引入未验证的 smoothing、prominence 或“重要节点”打分。若原始节点噪声过大，应先以研究输出观察，再单独定义升级方案。

## 7. Profile 类型与更新能力

| 能力 | 参考项目现状 | 当前项目未来可行性 |
| --- | --- | --- |
| Fixed Range | 调用 `mp[start:end]` 的任意连续索引切片 | 可直接实现为 `build_range_profile(start, as_of)` |
| Rolling | 无一等 API；调用方重复创建不同时间切片 | 可实现 VP20 / VP60，以实际交易日窗口裁剪 |
| Session | 无会话管理；open range / initial balance 只在给定切片首个时间戳上计算 | 未来在 1 分钟数据完整时可以按交易日构建；日线不能形成日内 Session VP |
| Composite | 无显式支持；只能先由调用方拼好 DataFrame | 可由显式日期集合/范围构建，不应由 UI 可见范围隐式决定 |
| Incremental update | 无 | V1 先完整重建以保证正确；后续只对 append-only 完整 bars 引入缓存/增量 |
| Developing POC / VA | 无 | 通过按连续 `as_of` 构建 profile 序列得到，不能由单个结果臆造 |

因此 VP20 = 截至 `as_of` 的最近 20 个有效交易日；VP60 同理。`WyckoffRangeVP` 的起点由现有 Wyckoff Trading Range 结构在 `as_of` 时已经确认的开始日提供，终点恒为 `as_of`；若起点未知、晚于终点或区间数据不足，返回不可用质量，不回退到未来确认的 range。

## 8. Non-repainting / look-ahead 审计

参考库不主动读取未来 K 线：`MarketProfileSlice` 只处理调用方传入的索引切片。但它没有 `as_of` 参数、交易日对齐、防未来检查、缓存键或 prefix-equality 测试。切片范围由调用方决定；当 UI 的 visible range 发生变化时，POC/VA/HVN/LVN 也会变化。这不是库内部的未来函数，却会使“同一天的指标”因展示窗口变化而重绘。

当前项目的强制规则应为：

1. 所有公开构建请求必须包含 `as_of`；引擎在计算前再次过滤 `bar_time <= as_of_cutoff`，不信任调用方预过滤；
2. 日线信号在收盘后才可包含当日日 K；盘中仅允许完整结束的分钟 K，不能包含尚未收盘的分钟 K；
3. VP20/VP60 的交易日窗口只能从 `as_of` 往前取；WyckoffRange 起点也只能取 `as_of` 时已可知的结构；
4. 可视范围仅影响图表，不得隐式改变策略/研究 profile；计算 profile 的 range、价格口径、bin 参数和 `as_of` 都写入缓存键与 DTO；
5. 每次 profile 重建必须是纯函数；相同输入得到相同输出；
6. 测试必须做 prefix equality：全样本先过滤至 D 的结果，必须等于只提供 D 及以前 bars 的结果；再加入 D+1 以后 bars 不得改变 D 的结果；
7. 缺 bar、停牌、分钟覆盖不足或价格口径不一致时 fail-closed，不能用未来 bars 补齐。

## 9. 当前项目实际行情能力

以下为本地 `data/` 与现有仓储接口的实际审计结果，而非仅由类型定义推断：

| 数据 | 存储与接口 | 本地覆盖 / 字段 | VP 含义 |
| --- | --- | --- | --- |
| 日线 | `kline_daily`；`KlineRepository.get_daily()` | 1,454 个日分区，2020-09-14 至 2026-09-11；`symbol,date,open,high,low,close,volume,amount` | 可支持日线近似 VP20/60/Range |
| enriched 日线 | `kline_daily_enriched`；同仓储读取 | 相同 1,454 分区；前复权 OHLC，另有 `raw_close/raw_high/raw_low,turnover_rate` | 可作上下文；VP 需明确 price basis，不能混用 raw/adjusted |
| 通用 1 分钟 | `kline_minute`；`get_minute()` / `get_minute_range()` | 34 个日分区；2025-04-17 的局部片段及 2026-08 至 2026-09 的少量单标的片段；OHLCV/amount | 接口已具备，但本地历史覆盖不足以作为全候选 VP 的默认来源 |
| CZSC 原生分钟 | `kline_czsc_minute`；`get_czsc_minute_range()` | 15m/30m/60m 各 304 日分区，2025-06-17 至 2026-09-10；OHLCV/amount | 可用于按需研究，但不应让通用 VP 依赖 CZSC 专用存储 |
| 深度 | `depth5` 能力与 DuckDB view 已预留 | 本地没有 parquet；仅五档盘口快照能力，不是历史成交明细 | 不可用于构造历史 VAP |
| 逐笔 / tick trades | 未发现标准数据集、仓储方法或本地存储 | 不存在 | 暂不支持精确 VAP |

分钟数据的标准时间契约是北京时间墙钟、naive `datetime`；通用分钟 K 固定为 1m。接口和 Provider 层确实支持 `minute` / `full_minute` 路由，但能否使用取决于当前数据源能力；本机已落盘数据不能被误称为全市场完整分钟历史。

### 价格口径

VP 的 high/low/close 必须处于同一价格坐标。日线 raw 数据有原始 OHLCV；enriched 则为前复权 OHLC，并附 raw close/high/low。对于“当前分析”可以使用统一的前复权输入；但历史研究必须构造**以 as_of 为基准的同一复权坐标**，而非把未来除权因子回写进历史 profile。未来 Data Adapter 应显式输出 `price_basis`、`adjustment_as_of` 和质量说明；不能把 raw 与前复权字段混在同一 profile。

## 10. 方案比较

| 方案 | 评价 |
| --- | --- |
| A. 直接依赖参考项目 | 不推荐。pandas/scipy 依赖、Close-at-Price 误差、无 as-of 契约、无项目 Provider/Polars/DTO 对齐；还会把第三方 API 选择带入核心链路。 |
| B. 复制核心源码后修改 | 不推荐。会继承其 DataFrame/float/Close 分配假设，形成难以追踪的 fork，且仍须重写主要数据、质量和防重绘边界。 |
| C. 理解后内部构建 `VolumeProfileEngine` | 推荐。复用现有 Provider、`KlineRepository`、Polars 与数据质量约定；把日线、1m、未来逐笔以同一 input contract 接入，并保留参考实现可解释的 POC/Value Area 语义。 |

## 11. 推荐的 VolumeProfileEngine 架构（设计，不实现）

建议新增独立纯计算模块 `backend/app/services/volume_profile.py`，不直接访问 UI、StrategyEngine 或参考目录。数据读取由一个薄的 `VolumeProfileDataResolver` 负责，走现有 Provider / `KlineRepository`；引擎只接收已标准化、已排序、已执行 as-of 截断的 bars。该边界使数据粒度可由日线升级到 1 分钟或逐笔，而调用层不变。

```text
KlineRepository / Provider
  -> VolumeProfileDataResolver (asset、price basis、as_of、质量与覆盖检查)
  -> VolumeProfileEngine (纯函数：分桶、VAP、POC、VA、nodes)
  -> VolumeProfileResult (DTO)
  -> 研究 / Wyckoff 候选上下文 / 未来图表
```

建议能力：

```python
build_profile(bars, request) -> VolumeProfileResult
build_rolling_profile(bars, *, as_of, sessions, request) -> VolumeProfileResult
build_range_profile(bars, *, start, as_of, request) -> VolumeProfileResult
```

其中 `request` 至少包括 `symbol`、`asset_type`、`as_of`、`price_basis`、`bar_granularity`、`tick_size`、`target_bin_count`、`value_area_pct`、数据开始/结束范围。Engine 不应自行猜测 Wyckoff Range 起点、不应调用筛选器，也不应输出买卖信号。

建议 `VolumeProfileResult`：

```text
symbol, asset_type, profile_kind, source_granularity, price_basis
as_of, data_start, data_end, current_price

poc, poc_bin_lower, poc_bin_upper, poc_volume
vah, val, value_area_width, value_area_volume_ratio
distance_to_poc_pct, distance_to_vah_pct, distance_to_val_pct

profile_low, profile_high, bin_width, bin_count
bins[]: lower, upper, center, volume, volume_ratio
hvn_levels[], lvn_levels[]

quality: status, bar_count, expected_bar_count, coverage_ratio,
         missing_sessions, unavailable_reasons
```

`quality` 至少区分 `COMPLETE`、`PARTIAL`、`INSUFFICIENT`、`UNAVAILABLE`。日线可用不等于分钟 profile 可用；数据源、频率、缺交易日、复权基准和 bin 参数都要进入缓存键。

## 12. VP20 / VP60 / WyckoffRangeVP

| Profile | 输入范围 | V1 数据优先级 | 质量要求 |
| --- | --- | --- | --- |
| VP20 | `as_of` 向前最近 20 个有效交易日 | 日线 VAP 近似；完整 1m 覆盖时自动提高精度 | 有效日不足 20 或中间缺失应标记 PARTIAL/INSUFFICIENT |
| VP60 | `as_of` 向前最近 60 个有效交易日 | 同上 | 不将自然日误作交易日；企业行动 price basis 必须一致 |
| WyckoffRangeVP | Trading Range 起点至 `as_of` | 同上 | 起点必须为 as-of 时已确认的 Wyckoff range；无起点不计算 |

V1 不做复杂增量缓存；先用完整重建和 prefix-equality 测试证明正确。后续若 profile range 固定、仅追加完整 bar，可缓存 bin accumulation；只要出现历史修订、拆并复权、bin 参数或 range 变化，就必须失效重建。

## 13. 动态 VP 与未来状态设计

动态字段来自同一种 profile 在连续 as-of 下的**已完成历史序列**：

```text
poc_change_N = poc(D) - poc(D-N)
poc_slope_N  = 对最近 N 个有效 POC 做线性斜率（需记录样本数）
vah_change_N = vah(D) - vah(D-N)
val_change_N = val(D) - val(D-N)
value_area_shift_N = (vah_change_N, val_change_N, width_change_N)
```

`POC_RISING/FLAT/FALLING` 与 `VALUE_AREA_RISING/STABLE/FALLING` 必须基于显式的最小有效变动（至少 tick / bin width）和最少 snapshot 数，而不是价格浮点噪声。状态阈值与原始变化量都必须输出；本阶段不定义策略动作。

未来位置语义：

| 状态 | 只读定义方向 |
| --- | --- |
| WITHIN_VALUE | `VAL <= price <= VAH` |
| NEAR_POC / NEAR_VAH | 与 POC/VAH 距离不超过显式的 bin/波动尺度容差 |
| ABOVE_VAH / BELOW_VAL | 价格越过当前 Value Area 边界；仅位置描述，不代表多空信号 |
| ABOVE_VAH_ACCEPTED | 相对突破前的冻结 VAH，随后截至 as-of 的已完成 bars 多次收于其上，且突破后 VAP/POC 或 Value Area 也向上迁移；不得只看 `price > VAH` |
| ABOVE_VAH_EXTENDED | 价格高于 VAH 且与 POC/VAH 的距离较大，但 POC/Value Area 未同步上移或上方成交接受不足 |

Acceptance 需要一个“突破前 profile”作为基线，及从突破日到 `as_of` 的已完成 bars。这样可在 D 日描述 D 日前的接受过程，不使用 D 后数据；若没有足够后的已完成 bars，应返回 `UNCONFIRMED`，不能武断归类为 accepted 或 failed。

未来可设计、但不设权重的上下文分解：

```text
PositionScore       # 相对 POC/VAH/VAL 的位置与 Value Area 宽度
AcceptanceScore     # 上方/下方是否已形成成交与 VA/POC 迁移
ExtensionPenalty    # 远离 POC/VAH、而接受不足的风险

VPScore = PositionScore + AcceptanceScore - ExtensionPenalty
```

这只是将来研究接口；本阶段不输出正式 VP Score，不给任何候选加减分。

## 14. 与 Sector / RS / NARROWING 的未来结合

Sector/RS/NARROWING 描述的是强度、相对强弱和内部扩散状态，不能说明价格上方是否已形成稳定成交接受。VP 可补充该缺口：

| 场景 | VP 应观察的事实 | 正确表述 |
| --- | --- | --- |
| 健康集中 | NARROWING + 个股强，但 POC 与 VAL/VAH 上移，且高位有连续完成 bars 与 VAP 接受 | 与“资金向核心股集中、在更高价格重新形成交易区”一致；不是买入结论 |
| 末端抱团 | 高 RS / 高分，但价位远离 VAH/POC，POC 未跟随、VA 未抬升，上方成交不足 | 与“末端延展或抱团风险”一致；不是自动看空结论 |

因此未来 VP 只应作为 Wyckoff 已筛出的候选的**位置、接受、延展上下文**。在独立验证前，不能把它接入 `final_rank_score`，也不能因 `NARROWING` 或 `ABOVE_VAH` 自动改变候选优先级。

## 15. 第一版建议实现范围

1. 建立项目内纯 `VolumeProfileEngine`、DTO、日线 Data Resolver 和完整单元测试；
2. 支持 `build_profile`、VP20、VP60、WyckoffRangeVP，使用按 high~low bin overlap 的成交量守恒近似；
3. 输出 POC、VAL/VAH、profile bins、严格局部 HVN/LVN、距离字段与质量；
4. 实现 as-of 截断、交易日窗口与 prefix-equality / future-bar 无影响测试；
5. 当完整 1m 覆盖真实可用时，以相同 DTO 增加 1m 输入路径；无覆盖时保持日线质量标签，不静默混合频率；
6. 暂不实现 VP Score、正式候选排序、买卖规则、L2/逐笔依赖、CZSC 接线或 UI 图表。

后续正式开发应先阅读本文，再定位现有 `KlineRepository`、Provider 数据契约与 Sector/RS 上下文代码；不需要重新全量扫描本参考项目。

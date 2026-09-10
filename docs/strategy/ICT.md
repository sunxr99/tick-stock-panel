# ICT / SMC 源码研究

## 范围与输入

唯一核心算法文件为 `smartmoneyconcepts/smc.py`；输入是按时间升序、DatetimeIndex 的 pandas OHLCV（OB、previous-high-low 使用 volume）。库不做复权、时区或输入排序治理，项目 Adapter 必须负责。它提供结构标注，不提供仓位、止损或交易策略。

| 函数 | 输出 | Volume | 未来数据 / 回看风险 | 用途 |
|---|---|---:|---|---|
| `swing_highs_lows` | HighLow, Level | 否 | **高**：左右各 `swing_length` 根确认，且首尾被强制补点 | 结构、绘图 |
| `bos_choch` | BOS, CHOCH, Level, BrokenIndex | 否 | **高**：依赖 Swing，且只保留后来实际突破的结构 | 结构确认 |
| `fvg` | FVG, Top, Bottom, MitigatedIndex | 否 | **高**：识别当前 bar 时读取 `t+1`；mitigation 还扫描未来 | 区域绘图、风险 |
| `ob` | OB, Top, Bottom, OBVolume, MitigatedIndex, Percentage | 是 | **高**：OB 画在历史候选蜡烛，创建依赖后来收盘突破；失效状态也回写 | 区域绘图、评分特征 |
| `liquidity` | Liquidity, Level, End, Swept | 否 | **高**：聚类和 sweep 都查询以后 bar | 流动性风险 |
| `previous_high_low` | PreviousHigh/Low, BrokenHigh/Low | 是（重采样） | 低；只应使用已闭合上级周期 | 日/周/月关键位 |
| `sessions` | Active, High, Low | 否 | 低（累计会话内值） | 分钟K时段过滤 |
| `retracements` | Direction, Current/DeepestRetracement | 否 | 继承 Swing 的高风险 | 辅助特征 |

## 源码规则

- Swing：当前 high/low 必须是前后各 `swing_length` 窗口极值，随后循环清除连续同向点中较弱者。因此 `event_time` 是极值 K，`confirmation_time` 至少是 `event_time + swing_length`，最后一个补点更不能用于回测。
- BOS/CHoCH：先从四个交替 Swing 构造 HH/HL 或 LL/LH 的排列；Bullish/Bearish BOS 与 CHoCH 都把结构归档在倒数第二个 Swing，之后从 `i+2` 找首根 `close_break=True` 时收盘、否则 high/low 突破该 Level 的 K。应将 `BrokenIndex` 映射为 confirmation_time，而非把标记日当成交日。
- FVG：Bullish 条件为 `high[t-1] < low[t+1] && close[t] > open[t]`；Bearish 对称。边界为两侧蜡烛的 high/low；连续同向可合并为最高 Top、最低 Bottom。首次随后 low≤Top（多）/high≥Bottom（空）记录 MitigatedIndex。
- OB：收盘上破最近 Swing High 时，取该 Swing 与突破K之间最后一个最低 low 的整根K为 Bullish OB；下破最近 Swing Low 对称取最后一个最高 high。OBVolume 为突破K及前两K成交量，Percentage 是两段成交量的 min/max 比，不是预测胜率；跌破 Bottom/上破 Top 后记 mitigation，随后反向再穿越会删除历史 OB。
- Liquidity：同向 Swing 的 Level 落在全样本 `(max(high)-min(low))*range_percent` 阈值内、至少两点，即形成等高（值 1）/等低（值 -1）流动性；向上越过上界或向下越过下界为 Swept。它不等价于可交易的 sweep reversal。

## 接入结论

分钟K比日K更适合 session、FVG、OB 与流动性；日K可用于上级关键位/大结构。不要把 BOS、CHoCH、OB、FVG 或 sweep 单独翻译为 BUY/SELL。Adapter 必须逐bar滚动计算，分别输出 `event_time`、`confirmation_time`、`status=confirmed|active|mitigated|invalidated`；离线全序列输出仅可用于复盘绘图。

## Docs First 补充：作者公开边界与源码差异

作者 `README.md` 只公开八个指标：FVG、Swing、BOS/CHoCH、OB、Liquidity、Previous High/Low、Sessions、Retracements；`smc.py::smc` 恰有八个同名 classmethod，公开能力为 **VERIFIED**。仓库没有公开或实现仓位、事件组合、执行、止损或回测引擎，因此不能将其称为完整 ICT 策略。

README 对数据要求是小写 `open/high/low/close`，并指出仅需要 OHLCV 的指标才要求 `volume`；源码进一步表明 `ob` 明确读取 volume，其他结构函数并不需要。作者文档未表达最重要的时间边界：FVG 直接读取 `t+1`，Swing 使用右侧窗口，BOS/CHoCH/OB/Liquidity 随后把确认结果写回早期结构索引。`BrokenIndex` 和 `MitigatedIndex` 是有用的后续位置，却不是原库提供的标准 `confirmation_time`；未来 Adapter 必须转换，不能把 DataFrame 行位置直接当作触发时点。

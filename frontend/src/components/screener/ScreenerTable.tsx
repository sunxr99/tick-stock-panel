/**
 * 策略结果表格。
 *
 * 表格骨架（表头排序/sticky/遍历）由共享的 StockDataTable 承担；本组件只负责
 * 策略页特有的单元格内容：symbol 列（含加自选按钮 + 失效行灰显）、strategies、
 * score、signals、candle、ext 列。其余纯数据列（价格/指标/财务…）交给共享原语。
 */
import { useState, type CSSProperties, type ReactNode } from 'react'
import { Check, Plus, Eye, EyeOff, RefreshCw, ListCollapse, ListTree } from 'lucide-react'
import type { KlineRow, MinuteKlineRow } from '@/lib/api'
import { fmtPrice, formatExtNumber } from '@/lib/format'
import type { ColumnConfig } from '@/lib/screener-columns'
import { getSignals, signalCls } from '@/lib/stock-table'
import { boardTag, renderBuiltinDataCell } from '@/components/stock-table/primitives'
import { resolveCandleConfig, resolveIntradayConfig } from '@/lib/list-columns'
import { MiniCandlestick } from '@/components/stock-table/MiniCandlestick'
import { MiniIntraday } from '@/components/stock-table/MiniIntraday'
import { StockDataTable, type SortState } from '@/components/stock-table/StockDataTable'
import { WatchlistAddMenu } from '@/components/WatchlistAddMenu'
import {
  DimensionMembersDialog,
  dimensionKindForSourceField,
  type DimensionMembersTarget,
} from '@/components/DimensionMembersDialog'
import { toNavItems, type NavItem } from '@/components/StockPreviewDialog'
import { cn } from '@/lib/cn'

const VP_RISK_BADGE: Record<string, { label: string; className: string; groupLabel: string }> = {
  EXTREME: { label: '极高风险', className: 'border-rose-500/30 bg-rose-500/10 text-rose-300', groupLabel: '🔥 EXTREME · 高动量 / 高路径风险' },
  HIGH: { label: '高风险', className: 'border-orange-400/30 bg-orange-400/10 text-orange-300', groupLabel: '⚠ HIGH · 强趋势 / 较高路径风险' },
  MEDIUM: { label: '中等风险', className: 'border-sky-400/30 bg-sky-400/10 text-sky-300', groupLabel: 'MEDIUM · 中等扩张' },
  LOW: { label: '低风险', className: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300', groupLabel: 'LOW · 位置相对温和' },
  UNKNOWN: { label: '未知', className: 'border-slate-400/30 bg-slate-400/10 text-slate-300', groupLabel: 'UNKNOWN · VP 数据质量不足' },
}

function vpRiskDetail(row: Record<string, unknown>): string {
  const riskScore = row.vp_risk_score == null ? '—' : `${Number(row.vp_risk_score).toFixed(0)} / 100`
  return [
    `VP Risk：${row.vp_risk_bucket ?? 'UNKNOWN'}（${riskScore}）`,
    `VP20 延展：${row.vp20_extension ?? '—'}｜VP60 延展：${row.vp60_extension ?? '—'}`,
    `VP20 位置：${row.vp20_position ?? '—'}｜VP60 位置：${row.vp60_position ?? '—'}`,
    `Sector V2：${row.sector_score_v2 ?? row.sector_score ?? '—'}｜RS V2：${row.rs_score_v2 ?? row.rs_score ?? '—'}`,
    '风险路由仅描述路径风险，不构成买卖建议。',
  ].join('\n')
}

interface ScreenerTableProps {
  rows: any[]
  columns: ColumnConfig[]
  strategyIdToName: Record<string, string>
  symbolStrategyMap: Map<string, string[]>
  activeStrategy: string | null
  watchlistSet: Set<string>
  onPreview: (symbol: string, name?: string, navList?: NavItem[]) => void
  onAddToWatchlist: (symbol: string, groupId: string | null) => void
  onRemoveFromWatchlist: (symbol: string) => void
  watchlistPending: boolean
  /** symbol → 日k 数据，仅当启用日k列时传入 */
  klineData?: Record<string, KlineRow[]>
  /** 日k蜡烛图是否显示（表头眼睛开关） */
  dailyKChartVisible?: boolean
  onToggleDailyKChart?: () => void
  /** symbol → 分时数据，仅当启用分时列时传入 */
  minuteData?: Record<string, MinuteKlineRow[]>
  /** 分时图是否显示（表头眼睛开关） */
  intradayChartVisible?: boolean
  onToggleIntradayChart?: () => void
  /** 分时是否正在自动轮询 (true 时隐藏手动刷新按钮, 避免重复请求) */
  intradayAutoRefresh?: boolean
  /** 手动刷新分时数据 */
  onRefreshIntraday?: () => void
  /** 分时数据正在刷新中 (按钮 loading 态) */
  intradayRefreshing?: boolean
  /** 策略列标签全表展开状态 (false=默认收起: 每行仅显示首个策略+计数) */
  strategyTagsExpanded?: boolean
  /** 表头策略列图标: 切换全表展开/收起 */
  onToggleStrategyTags?: () => void
  /** 表头排序（受控，由 Screener.tsx 传入） */
  sort?: SortState | null
  onSortToggle?: (colId: string) => void
  /** 正在 K 线弹窗预览中的 symbol → 高亮该行 */
  activeSymbol?: string | null
}

/** 渲染标签数组（含 maxTags 折叠/展开、横竖排列）。策略列与 ext 列共用。
 *  maxTagsOverride: 调用方直接指定折叠上限 (策略列用: 全局展开=0 不折叠, 收起=1 只显首个)。 */
function renderTagList(
  tags: string[],
  col: ColumnConfig,
  expanded: boolean,
  onToggle: () => void,
  tagClassName: string,
  onTagClick?: (tag: string) => void,
  maxTagsOverride?: number,
): ReactNode {
  if (tags.length === 0) return <span className="text-muted">—</span>

  const cfg = col.extDisplay
  const maxTags = maxTagsOverride ?? cfg?.maxTags ?? 0
  const showAll = maxTags <= 0 || expanded || tags.length <= maxTags
  const sliced = showAll ? tags : tags.slice(0, maxTags)
  const hiddenIndices = maxTags > 0 ? cfg?.hiddenIndices : undefined
  const visibleTags = hiddenIndices?.length
    ? sliced.filter((_, i) => !hiddenIndices.includes(i))
    : sliced
  const hiddenCount = tags.length - visibleTags.length
  // 排列方向始终跟随列设置: 竖向时收起/展开都竖排, 展开不再强制横向
  const isVertical = cfg?.tagLayout === 'vertical'

  return (
    <div className={isVertical ? 'flex flex-col items-start gap-0.5' : 'flex flex-wrap gap-0.5'}>
      {visibleTags.map((tag, i) => onTagClick ? (
        <button
          key={i}
          type="button"
          onClick={event => { event.stopPropagation(); onTagClick(tag) }}
          className={`${tagClassName} hover:brightness-95`}
        >
          {tag}
        </button>
      ) : (
        <span key={i} className={tagClassName}>{tag}</span>
      ))}
      {!showAll && hiddenCount > 0 && (
        <button
          onClick={onToggle}
          className="inline-block px-1.5 py-px rounded text-[10px] font-medium leading-tight text-accent bg-accent/10 hover:bg-accent/20 transition-colors"
        >
          +{hiddenCount}
        </button>
      )}
      {showAll && maxTags > 0 && tags.length > maxTags && (
        <button
          onClick={onToggle}
          className="inline-block px-1.5 py-px rounded text-[10px] font-medium leading-tight text-muted hover:text-foreground transition-colors"
        >
          收起
        </button>
      )}
    </div>
  )
}

const EXT_TAG_CLS = 'inline-block px-1.5 py-px rounded text-[10px] font-medium leading-tight text-yellow-500 bg-yellow-500/10'
const STRATEGY_TAG_CLS = 'inline-block px-1.5 py-px rounded text-[10px] font-medium leading-tight bg-amber-500/10 text-amber-600 border border-amber-500/20'
const WYCKOFF_FUNNEL_ID = 'wyckoff_funnel'

function fmtRankingNumber(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '—'
}

function fmtRankingPercent(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '—'
}

function fmtRankingInteger(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value)) : '—'
}

function contextOf(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

const PHASE_REASON_LABELS: Record<string, string> = {
  score_high: '板块绝对强度高',
  score_not_yet_high: '板块尚未进入极高分区',
  score_improving: '板块分数正在提升',
  score_not_improving: '板块分数未继续提升',
  score_change_negative: '板块分数下降',
  rank_improving: '板块排名提升',
  rank_falling: '板块排名下降',
  breadth_expanding: '内部上涨扩散',
  breadth_contracting: '内部强度收缩',
  breadth_healthy: '内部扩散健康',
  breadth_stable: '内部扩散稳定',
  extension_high: '板块价格延展较高',
  extension_not_extreme: '板块未处极端延展',
  state_history_incomplete: '历史数据不足，无法判定阶段',
  no_fixed_phase_condition: '不符合固定板块阶段条件',
}
const RS_REASON_LABELS: Record<string, string> = {
  rs_high: '个股相对强度高',
  rs_not_yet_high: '个股尚未进入高 RS 区间',
  rs_not_high: '个股相对强度不高',
  rs_improving: '个股相对强度正在提升',
  rs_falling: '个股相对强度下降',
  rs_change_flat: '个股相对强度横向稳定',
  extension_high: '个股价格延展较高',
  state_history_incomplete: '历史数据不足，无法判定个股状态',
  state_history_not_requested: '未请求状态历史',
}
const SECTOR_PHASE_LABELS: Record<string, string> = {
  EMERGING: '刚开始转强',
  ACCELERATING: '强势加速',
  LEADING: '稳定领涨',
  EXHAUSTED: '高位衰竭风险',
  FADING: '强度退潮',
}
const RS_STATE_LABELS: Record<string, string> = {
  LOW: '相对强度偏弱',
  RISING: '相对强度上升',
  HIGH_AND_RISING: '高相对强度且上升',
  HIGH_AND_FLAT: '高相对强度但走平',
  HIGH_AND_FALLING: '高相对强度但下降',
  EXTENDED: '强势但明显延展',
}
const EXTENSION_LABELS: Record<string, string> = {
  NORMAL: '正常',
  ELEVATED: '偏高',
  EXTENDED: '明显延展',
  EXTREME: '极度延展',
}
const BREADTH_LABELS: Record<string, string> = {
  EXPANDING: '内部强度扩散',
  STABLE: '内部强度稳定',
  CONTRACTING: '内部强度收缩',
}
const RESEARCH_CONTEXT_LABELS: Record<string, string> = {
  POSITIVE_STATE: '强势增强状态（仅研究）',
  NEUTRAL_STATE: '强势稳定状态（仅研究）',
  RISK_STATE: '过热或退潮风险（仅研究）',
  UNAVAILABLE: '数据不足，无法形成研究状态',
}
const RANKING_REASON_LABELS: Record<string, string> = {
  sector_emerging: '板块刚开始转强',
  sector_accelerating: '板块强势加速',
  sector_leading: '板块稳定领涨',
  sector_exhausted: '板块高位衰竭风险',
  sector_fading: '板块强度退潮',
  rs_rising: '个股相对强度上升',
  rs_high_and_rising: '个股高相对强度且上升',
  rs_high_and_falling: '个股高相对强度但下降',
  rs_extended: '个股强势但明显延展',
  rs_low: '个股相对强度偏弱',
  sector_extension_elevated: '板块延展偏高',
  sector_extension_extended: '板块明显延展',
  sector_extension_extreme: '板块极度延展',
  rs_extension_elevated: '个股延展偏高',
  rs_extension_extended: '个股明显延展',
  rs_extension_extreme: '个股极度延展',
}
const UNAVAILABLE_REASON_LABELS: Record<string, string> = {
  sector_strength_unavailable: '板块强度结果不可用',
  relative_strength_unavailable: '个股相对强度结果不可用',
  industry_membership_missing: '缺少一级行业归属',
  multiple_industry_contexts: '存在多个一级行业归属，无法自动选择',
  sector_or_relative_strength_incomplete: '板块分或个股 RS 不完整',
  dynamic_state_incomplete: '强度变化、广度或延展状态数据不完整',
  extension_state_incomplete: '延展状态数据不完整',
}

function chineseReasons(value: unknown, labels: Record<string, string>): string {
  if (!Array.isArray(value) || value.length === 0) return '—'
  return value.map(item => labels[String(item)] ?? String(item)).join('；')
}

function chineseLabel(value: unknown, labels: Record<string, string>, fallback = '—'): string {
  return labels[String(value)] ?? (value == null ? fallback : String(value))
}

function wyckoffResearchDetail(row: Record<string, unknown>): string {
  const researchScore = row.research_context_score ?? row.final_rank_score
  const unavailableLines = researchScore == null
    ? [
      'Sector / RS 研究状态不可用',
      `原因：${chineseLabel(row.ranking_unavailable_reason, UNAVAILABLE_REASON_LABELS, '上下文数据不完整')}`,
      '该候选仍由 Wyckoff 漏斗保留；不因状态缺失被删除或降分。',
      '',
    ]
    : []
  const reasons = Array.isArray(row.ranking_reasons) && row.ranking_reasons.length
    ? row.ranking_reasons.map(item => chineseLabel(item, RANKING_REASON_LABELS)).join('、')
    : '无额外正向状态'
  const risks = Array.isArray(row.risk_reasons) && row.risk_reasons.length
    ? row.risk_reasons.map(item => chineseLabel(item, RANKING_REASON_LABELS)).join('、')
    : '无明显状态风险'
  const sector = contextOf(row.sector_context)
  const rs = contextOf(row.rs_context)
  return [
    ...unavailableLines,
    '【Sector / RS 研究状态】不参与 Wyckoff 默认排序、策略评分或交易决策。',
    `研究上下文分：${fmtRankingNumber(researchScore)}（仅供后续候选池验证）`,
    `OpportunityScore V2（研究）：${fmtRankingNumber(row.opportunity_score_v2)} = SectorScore V2 ${fmtRankingNumber(row.sector_score_v2)} × 40% + RSScore V2 ${fmtRankingNumber(row.rs_score_v2)} × 60%；正式 OpportunityScore（Legacy）：${fmtRankingNumber(row.strength_score)}`,
    `行业层级：SW1 ${String(row.sw1_name ?? '—')}｜SW2 ${String(row.sw2_name ?? '—')}｜SW3 ${String(row.sw3_name ?? '—')}；可用性：SW2 ${row.sw2_available ? '可用' : '缺失'}｜SW3 ${row.sw3_available ? '可用' : '缺失'}；合成口径：${String(row.opportunity_score_basis ?? '—')}`,
    `Sector：SW2 ${fmtRankingNumber(row.sw2_sector_score)} × 70% + SW3 ${fmtRankingNumber(row.sw3_sector_score)} × 30% = ${fmtRankingNumber(row.sector_score_v2)}；SW1 仅保留研究值 ${fmtRankingNumber(row.sw1_sector_score)}；层级状态 ${String(row.sector_hierarchy_state ?? '—')}`,
    `RS：市场 ${fmtRankingNumber(row.market_rs)} × 40% + SW2 ${fmtRankingNumber(row.sw2_rs)} × 40% + SW3 ${fmtRankingNumber(row.sw3_rs)} × 20% = ${fmtRankingNumber(row.rs_score_v2)}；Legacy Sector/RS/Opportunity：${fmtRankingNumber(row.sector_score_legacy)} / ${fmtRankingNumber(row.rs_score_legacy)} / ${fmtRankingNumber(row.opportunity_score_legacy)}`,
    `状态修正：板块 ${fmtRankingNumber(row.sector_phase_adjustment)}｜个股 ${fmtRankingNumber(row.rs_state_adjustment)}；延展扣分：板块 -${fmtRankingNumber(row.sector_extension_penalty)}｜个股 -${fmtRankingNumber(row.rs_extension_penalty)}`,
    `状态标签：${chineseLabel(row.research_context_level, RESEARCH_CONTEXT_LABELS)}｜正向状态：${reasons}｜风险状态：${risks}`,
    '',
    `【板块当前强度】一级行业：${String(sector.name ?? '—')}｜成员覆盖：${fmtRankingInteger(sector.valid_member_count)}/${fmtRankingInteger(sector.member_count)}（${fmtRankingPercent(sector.coverage_ratio)}）`,
    `板块分：${fmtRankingNumber(sector.score)}｜排名：${fmtRankingInteger(sector.rank)}｜百分位：${fmtRankingNumber(sector.percentile)}`,
    `板块收益（3/5/10/20日）：${fmtRankingPercent(sector.return_3d)} / ${fmtRankingPercent(sector.return_5d)} / ${fmtRankingPercent(sector.return_10d)} / ${fmtRankingPercent(sector.return_20d)}`,
    `相对全市场收益（3/5/10/20日）：${fmtRankingPercent(sector.relative_return_3d)} / ${fmtRankingPercent(sector.relative_return_5d)} / ${fmtRankingPercent(sector.relative_return_10d)} / ${fmtRankingPercent(sector.relative_return_20d)}`,
    `板块原始分项：相对动量 ${fmtRankingNumber(sector.relative_momentum_score)}｜内部广度 ${fmtRankingNumber(sector.breadth_score)}｜持续强势 ${fmtRankingNumber(sector.persistence_score)}（${fmtRankingInteger(sector.persistence_days)}日）`,
    `内部参与：上涨成员 ${fmtRankingPercent(sector.up_ratio)}｜强势成员 ${fmtRankingPercent(sector.strong_stock_ratio)}｜广度状态 ${chineseLabel(sector.breadth_state, BREADTH_LABELS)}`,
    '',
    `【板块变化与延展】分数变化（1/3日）：${fmtRankingNumber(sector.score_change_1d)} / ${fmtRankingNumber(sector.score_change_3d)}｜百分位变化：${fmtRankingNumber(sector.percentile_change_1d)} / ${fmtRankingNumber(sector.percentile_change_3d)}｜排名变化：${fmtRankingNumber(sector.rank_change_1d)} / ${fmtRankingNumber(sector.rank_change_3d)}`,
    `内部参与变化（1/3日）：上涨成员 ${fmtRankingPercent(sector.up_ratio_change_1d)} / ${fmtRankingPercent(sector.up_ratio_change_3d)}；强势成员 ${fmtRankingPercent(sector.strong_stock_ratio_change_1d)} / ${fmtRankingPercent(sector.strong_stock_ratio_change_3d)}；5日排名波动 ${fmtRankingNumber(sector.rank_std_5d)}`,
    `板块延展：20日收益百分位 ${fmtRankingNumber(sector.return_20d_percentile)}｜偏离 MA20 ${fmtRankingPercent(sector.distance_from_ma20)}｜偏离 MA60 ${fmtRankingPercent(sector.distance_from_ma60)}｜连续上涨 ${fmtRankingInteger(sector.consecutive_up_days)}日｜延展分 ${fmtRankingNumber(sector.extension_score)}（${chineseLabel(sector.extension_state, EXTENSION_LABELS)}）`,
    `板块阶段：${chineseLabel(sector.phase, SECTOR_PHASE_LABELS, '未分类')}｜判定依据：${chineseReasons(sector.phase_reasons, PHASE_REASON_LABELS)}`,
    '',
    `【个股相对强度】个股 RS：${fmtRankingNumber(rs.rs_score)}｜市场 RS：${fmtRankingNumber(rs.market_rs_score)}（全市场排名 ${fmtRankingInteger(rs.market_rank)}，百分位 ${fmtRankingNumber(rs.market_percentile)}）｜行业 RS：${fmtRankingNumber(rs.sector_rs_score)}（行业排名 ${fmtRankingInteger(rs.sector_rank)}，百分位 ${fmtRankingNumber(rs.sector_percentile)}）`,
    `个股收益（3/5/10/20/60日）：${fmtRankingPercent(rs.stock_return_3d)} / ${fmtRankingPercent(rs.stock_return_5d)} / ${fmtRankingPercent(rs.stock_return_10d)} / ${fmtRankingPercent(rs.stock_return_20d)} / ${fmtRankingPercent(rs.stock_return_60d)}`,
    `跑赢全市场（3/5/10/20/60日）：${fmtRankingPercent(rs.vs_market_3d)} / ${fmtRankingPercent(rs.vs_market_5d)} / ${fmtRankingPercent(rs.vs_market_10d)} / ${fmtRankingPercent(rs.vs_market_20d)} / ${fmtRankingPercent(rs.vs_market_60d)}`,
    `跑赢所属行业（3/5/10/20/60日）：${fmtRankingPercent(rs.vs_sector_3d)} / ${fmtRankingPercent(rs.vs_sector_5d)} / ${fmtRankingPercent(rs.vs_sector_10d)} / ${fmtRankingPercent(rs.vs_sector_20d)} / ${fmtRankingPercent(rs.vs_sector_60d)}`,
    '',
    `【个股变化与延展】RS 变化（1/3日）：${fmtRankingNumber(rs.rs_change_1d)} / ${fmtRankingNumber(rs.rs_change_3d)}｜市场 RS 3日变化：${fmtRankingNumber(rs.market_rs_change_3d)}｜行业 RS 3日变化：${fmtRankingNumber(rs.sector_rs_change_3d)}`,
    `排名变化（3日）：全市场 ${fmtRankingNumber(rs.market_rank_change_3d)}｜行业 ${fmtRankingNumber(rs.sector_rank_change_3d)}`,
    `个股延展：20日收益百分位 ${fmtRankingNumber(rs.stock_return_20d_percentile)}｜偏离 MA20 ${fmtRankingPercent(rs.distance_from_ma20)}｜偏离 MA60 ${fmtRankingPercent(rs.distance_from_ma60)}｜连续上涨 ${fmtRankingInteger(rs.consecutive_up_days)}日｜延展分 ${fmtRankingNumber(rs.rs_extension_score)}（${chineseLabel(rs.rs_extension_state, EXTENSION_LABELS)}）`,
    `个股状态：${chineseLabel(rs.rs_state, RS_STATE_LABELS)}｜判定依据：${chineseReasons(rs.state_reasons, RS_REASON_LABELS)}`,
  ].join('\n')
}

function renderExtValue(
  val: any,
  col: ColumnConfig,
  expanded: boolean,
  onToggle: () => void,
  onTagClick?: (tag: string) => void,
): ReactNode {
  if (val == null || Number.isNaN(val)) return <span className="text-muted">—</span>
  if (typeof val === 'number') {
    // 数字格式化: 千分位 + 单位换算 + 小数位(由列配置控制)
    const cfg = col.extDisplay
    const hasNumFmt = cfg?.thousandSeparator || (cfg?.unitConvert && cfg.unitConvert !== 'none')
    const displayVal = hasNumFmt
      ? formatExtNumber(val, { thousandSeparator: cfg?.thousandSeparator, unitConvert: cfg?.unitConvert, unitDecimals: cfg?.unitDecimals })
      : (Number.isInteger(val) ? fmtPrice(val, 0) : fmtPrice(val))
    return <span className="tabular-nums">{displayVal}</span>
  }
  if (typeof val === 'boolean') {
    return <span className={val ? 'text-bull' : 'text-muted'}>{val ? '是' : '否'}</span>
  }

  const cfg = col.extDisplay
  const str = String(val)
  if (cfg?.displayMode === 'text') return <span className="text-foreground">{str}</span>

  const separator = cfg?.separator?.trim() || null
  const tags = separator
    ? str.split(separator).map(s => s.trim()).filter(Boolean)
    : str.split(/[、,，;；\-]/).map(s => s.trim()).filter(Boolean)

  return renderTagList(tags, col, expanded, onToggle, EXT_TAG_CLS, onTagClick)
}

export function ScreenerTable({
  rows, columns, strategyIdToName, symbolStrategyMap, activeStrategy,
  watchlistSet, onPreview, onAddToWatchlist, onRemoveFromWatchlist, watchlistPending, klineData = {},
  dailyKChartVisible = true, onToggleDailyKChart,
  minuteData = {}, intradayChartVisible = true, onToggleIntradayChart,
  intradayAutoRefresh = false, onRefreshIntraday, intradayRefreshing = false,
  strategyTagsExpanded = false, onToggleStrategyTags,
  sort, onSortToggle, activeSymbol,
}: ScreenerTableProps) {
  const [expandedCells, setExpandedCells] = useState<Set<string>>(new Set())
  const [dimensionTarget, setDimensionTarget] = useState<DimensionMembersTarget | null>(null)
  const riskGroupStarts = new Set<string>()
  if (activeStrategy === 'wyckoff_funnel') {
    let previousBucket: string | null = null
    for (const row of rows) {
      const bucket = String(row.vp_risk_bucket ?? 'UNKNOWN')
      if (bucket !== previousBucket) riskGroupStarts.add(String(row.symbol))
      previousBucket = bucket
    }
  }

  // 日k列渲染尺寸（按眼睛开关取开启/收起尺寸）
  const candleCol = columns.find(c => c.source.type === 'builtin' && c.source.key === 'candle' && c.visible)
  const candleResolved = resolveCandleConfig(candleCol?.candleConfig)
  const candleSize = dailyKChartVisible
    ? { width: candleResolved.enabledWidth, height: candleResolved.enabledHeight }
    : { width: candleResolved.disabledWidth, height: candleResolved.disabledHeight }

  // 分时列渲染尺寸（开启用配置宽高，收起用 40×40 占位，与自选页一致）
  const intradayCol = columns.find(c => c.source.type === 'builtin' && c.source.key === 'intraday' && c.visible)
  const intradayResolved = resolveIntradayConfig(intradayCol?.intradayConfig)
  const intradaySize = intradayChartVisible
    ? { width: intradayResolved.width, height: intradayResolved.height }
    : { width: 40, height: 40 }

  const toggleExpand = (key: string) => {
    setExpandedCells(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // 策略列全表切换: 收起时清除该列的行级展开状态, 保证"收起"立即对全表生效
  const strategiesColId = columns.find(c => c.source.type === 'builtin' && c.source.key === 'strategies')?.id
  const handleToggleStrategyTags = () => {
    if (strategyTagsExpanded && strategiesColId) {
      const suffix = `::${strategiesColId}`
      setExpandedCells(prev => {
        const next = new Set([...prev].filter(k => !k.endsWith(suffix)))
        return next.size === prev.size ? prev : next
      })
    }
    onToggleStrategyTags?.()
  }

  const renderCell = (r: any, col: ColumnConfig): ReactNode => {
    // ext 列
    if (col.source.type === 'ext') {
      const { configId, fieldName } = col.source
      const val = r[`${configId}__${fieldName}`]
      const cellKey = `${r.symbol}::${col.id}`
      const expanded = expandedCells.has(cellKey)
      const sourceField = `${configId}.${fieldName}`
      const dimensionKind = dimensionKindForSourceField(sourceField)
      const tdClass = val == null || Number.isNaN(val)
        ? 'px-3 py-2 text-center text-muted'
        : typeof val === 'number'
          ? 'px-3 py-2 text-right num tabular-nums'
          : 'px-3 py-2 text-center'
      const style: CSSProperties = {}
      if (col.extDisplay?.maxWidth) style.maxWidth = col.extDisplay.maxWidth
      return (
        <td key={col.id} className={tdClass} style={style}>
          {renderExtValue(
            val,
            col,
            expanded,
            () => toggleExpand(cellKey),
            dimensionKind ? value => setDimensionTarget({ kind: dimensionKind, value, sourceField }) : undefined,
          )}
        </td>
      )
    }

    const isExpired = !!r._expired
    const key = col.source.key

    // 策略页特有 / 需上下文的列
    switch (key) {
      case 'symbol': {
        const board = boardTag(r.symbol)
        const inWatchlist = watchlistSet.has(r.symbol)
        const riskBucket = activeStrategy === 'wyckoff_funnel'
          ? String(r.vp_risk_bucket ?? 'UNKNOWN')
          : null
        const riskPresentation = riskBucket ? VP_RISK_BADGE[riskBucket] ?? VP_RISK_BADGE.UNKNOWN : null
        const isRiskGroupStart = riskBucket != null && riskGroupStarts.has(String(r.symbol))
        return (
          <td key={col.id} className="px-4 py-2">
            {isRiskGroupStart && riskPresentation && (
              <div className="mb-1.5 text-[10px] font-semibold tracking-wide text-muted">
                {riskPresentation.groupLabel}
              </div>
            )}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onPreview(r.symbol, r.name ?? '', toNavItems(rows))}
                className={`flex items-center gap-2 text-left ${isExpired ? 'cursor-default' : ''}`}
              >
                {board ? (
                  <span className={`shrink-0 inline-flex items-center justify-center w-[18px] h-[18px] rounded text-[9px] font-bold leading-none border ${board.color}`}>
                    {board.label}
                  </span>
                ) : (
                  <span className="shrink-0 w-[18px]" />
                )}
                <span className="font-mono text-secondary group-hover:text-accent transition-colors duration-150 leading-snug">
                  {r.symbol}
                </span>
                {r.name && (
                  <span className="text-[11px] text-muted truncate group-hover:text-secondary transition-colors duration-150 leading-snug">
                    {r.name}
                  </span>
                )}
              </button>
              {riskPresentation && (
                <span
                  className={`shrink-0 rounded border px-1.5 py-px text-[10px] font-medium ${riskPresentation.className}`}
                  title={vpRiskDetail(r)}
                >
                  {riskPresentation.label}
                </span>
              )}
              {isExpired ? (
                <span className="shrink-0 inline-flex items-center px-1.5 py-px rounded text-[9px] font-medium leading-tight bg-red-500/10 text-red-400/60 border border-red-500/15">
                  失效
                </span>
              ) : (
                inWatchlist ? (
                  <button
                    type="button"
                    onClick={() => onRemoveFromWatchlist(r.symbol)}
                    disabled={watchlistPending}
                    className="shrink-0 inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-full border border-accent/40 bg-accent/10 text-accent transition-colors disabled:opacity-50"
                    title="移出自选"
                    aria-label={`将 ${r.symbol} 移出自选`}
                  >
                    <Check className="h-3 w-3" />
                  </button>
                ) : (
                  <WatchlistAddMenu
                    onSelect={groupId => onAddToWatchlist(r.symbol, groupId)}
                    disabled={watchlistPending}
                    triggerClassName="shrink-0 inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-full border border-border text-muted transition-colors hover:border-accent/40 hover:text-accent disabled:opacity-50"
                    ariaLabel={`将 ${r.symbol} 加入自选`}
                  >
                    <Plus className="h-3 w-3" />
                  </WatchlistAddMenu>
                )
              )}
            </div>
          </td>
        )
      }
      case 'strategies': {
        const strats = symbolStrategyMap.get(r.symbol) ?? (activeStrategy ? [activeStrategy] : [])
        const tags = strats.map(sid => strategyIdToName[sid] ?? sid)
        const cellKey = `${r.symbol}::${col.id}`
        const expanded = expandedCells.has(cellKey)
        // 收起时每行显示前N个 + "+N" 计数 (跟随列设置"显示前N个", 未配置默认 3),
        // 点击计数/收起按钮可单独展开/收起本行; 全局展开: maxTags=0 全部显示不折叠
        const cfgMaxTags = col.extDisplay?.maxTags ?? 0
        const maxTags = strategyTagsExpanded ? 0 : (cfgMaxTags > 0 ? cfgMaxTags : 3)
        return (
          <td key={col.id} className="px-3 py-2">
            {renderTagList(tags, col, expanded, () => toggleExpand(cellKey), STRATEGY_TAG_CLS, undefined, maxTags)}
          </td>
        )
      }
      case 'score': {
        const numCls = 'px-3 py-2 text-right num tabular-nums'
        const isWyckoff = activeStrategy === WYCKOFF_FUNNEL_ID
        const displayScore = r.score
        const scoreClass = displayScore >= 70
          ? 'text-accent font-medium'
          : displayScore >= 50
            ? 'text-amber-400'
            : 'text-secondary'
        return (
          <td key={col.id} className={numCls}>
            {isWyckoff ? (
              <span className="inline-flex items-center justify-end gap-1.5">
                <span className="text-muted">#{r.opportunity_rank ?? '—'}</span>
                <span
                  className="cursor-help text-accent font-medium"
                  title={`正式 OpportunityScore：Legacy（当前确定 Top150）。\n研究 OpportunityScore V2 = 40% SectorScore + 60% RSScore\nSector：SW2 70% + SW3 30% = ${r.sector_score_v2 ?? '—'}\nRS：Market 40% + SW2 40% + SW3 20% = ${r.rs_score_v2 ?? '—'}\nV2 仅展示与消融研究；VP 不参与扣分或过滤。\n\n${wyckoffResearchDetail(r)}`}
                  aria-label="查看 OpportunityScore 详情"
                >
                  {displayScore != null ? Number(displayScore).toFixed(1) : '—'}
                </span>
              </span>
            ) : displayScore != null ? (
              <span className="inline-flex items-center justify-end gap-1.5">
                <span className={scoreClass}>{Number(displayScore).toFixed(1)}</span>
              </span>
            ) : (
              <span className="inline-flex items-center justify-end gap-1.5">
                <span className="text-muted">—</span>
              </span>
            )}
          </td>
        )
      }
      case 'signals': {
        const signals = getSignals(r)
        return (
          <td key={col.id} className="px-3 py-2">
            {signals.length > 0 ? (
              <div className="flex flex-wrap gap-0.5">
                {signals.slice(0, 3).map((s) => (
                  <span key={s.label} className={`inline-block px-1.5 py-px rounded text-[10px] font-medium leading-tight ${signalCls(s.type)}`}>
                    {s.label}
                  </span>
                ))}
                {signals.length > 3 && (
                  <span className="text-[10px] text-muted">+{signals.length - 3}</span>
                )}
              </div>
            ) : (
              <span className="text-muted text-xs">—</span>
            )}
          </td>
        )
      }
      case 'candle': {
        const candleRows = klineData[r.symbol] ?? []
        // 锁定列宽与行高：minWidth=maxWidth 防止 kline 加载前后整列宽度跳动（闪烁）
        // padding/宽度与自选页一致（width+4 留内边距余量）
        return (
          <td
            key={col.id}
            className="pl-2 pr-3 py-1.5"
            style={{ width: candleSize.width + 4, minWidth: candleSize.width + 4, maxWidth: candleSize.width + 4, height: candleSize.height }}
          >
            <MiniCandlestick rows={candleRows} width={candleSize.width} height={candleSize.height} />
          </td>
        )
      }
      case 'intraday': {
        const rows: MinuteKlineRow[] = minuteData[r.symbol] ?? []
        const iw = intradaySize.width
        const ih = intradaySize.height
        // border-l 与自选页一致：当日k/分时相邻时提供视觉分隔
        return (
          <td
            key={col.id}
            className="pl-3 pr-2 py-1.5 border-l border-border/30"
            style={{ width: iw + 4, minWidth: iw + 4, maxWidth: iw + 4, height: ih }}
          >
            <div className="flex items-center justify-center">
              {intradayChartVisible
                ? <MiniIntraday rows={rows} prevClose={r.prev_close} changePct={r.change_pct} width={iw - 4} height={ih} />
                : <span className="text-[10px] text-muted">分时</span>}
            </div>
          </td>
        )
      }
      default:
        // 纯数据列 → 共享原语
        return renderBuiltinDataCell(r, col)
    }
  }

  return (
    <>
      <StockDataTable
        columns={columns}
        rows={rows}
        renderCell={renderCell}
        sort={sort}
        onSortToggle={onSortToggle}
        minWidth={Math.max(900, columns.filter(c => c.visible).length * 110)}
        rowKey={(r: any) => `${r.symbol}${r._expired ? '-expired' : ''}`}
        rowClassName={(r: any) => cn(
          r._expired
            ? 'border-border/50 opacity-40'
            : 'border-border hover:bg-elevated/50',
          r.symbol === activeSymbol && 'bg-accent/10',
        )}
        // 日k / 分时列表头：标签 + 显示/隐藏的眼睛按钮（与自选页一致）
        renderHeaderContent={(col) => {
        if (col.source.type !== 'builtin') return undefined
        const key = col.source.key
        if (key === 'score' && activeStrategy === WYCKOFF_FUNNEL_ID) {
          return <span title="当前 Top150 使用 Legacy OpportunityScore。SW2+SW3 V2 = 40% Sector(SW2 70% + SW3 30%) + 60% RS(Market 40% + SW2 40% + SW3 20%)，仅用于展示与消融研究；VP 仅作风险路由。">机会</span>
        }
        // 日k 蜡烛图开关
        if (key === 'candle' && onToggleDailyKChart) {
          return (
            <span className="inline-flex items-center justify-center gap-1.5">
              <span>{col.label}</span>
              <button
                type="button"
                onClick={(event) => { event.stopPropagation(); onToggleDailyKChart() }}
                className={`inline-flex items-center justify-center w-5 h-5 rounded transition-colors ${
                  dailyKChartVisible
                    ? 'text-accent bg-accent/10 hover:bg-accent/20'
                    : 'text-muted hover:text-foreground hover:bg-elevated'
                }`}
                title={dailyKChartVisible ? '隐藏日k蜡烛' : '显示日k蜡烛'}
                aria-label={dailyKChartVisible ? '隐藏日k蜡烛' : '显示日k蜡烛'}
              >
                {dailyKChartVisible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
              </button>
            </span>
          )
        }
        // 分时图开关 + 手动刷新按钮 (自动轮询开启时不显示, 避免重复请求)
        if (key === 'intraday' && onToggleIntradayChart) {
          return (
            <span className="inline-flex items-center justify-center gap-1.5">
              <span>{col.label}</span>
              <button
                type="button"
                onClick={(event) => { event.stopPropagation(); onToggleIntradayChart() }}
                className={`inline-flex items-center justify-center w-5 h-5 rounded transition-colors ${
                  intradayChartVisible
                    ? 'text-accent bg-accent/10 hover:bg-accent/20'
                    : 'text-muted hover:text-foreground hover:bg-elevated'
                }`}
                title={intradayChartVisible ? '隐藏分时图' : '显示分时图'}
                aria-label={intradayChartVisible ? '隐藏分时图' : '显示分时图'}
              >
                {intradayChartVisible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
              </button>
              {/* 分时图显示 且 未开自动轮询时, 提供手动刷新按钮 */}
              {intradayChartVisible && !intradayAutoRefresh && onRefreshIntraday && (
                <button
                  type="button"
                  onClick={(event) => { event.stopPropagation(); onRefreshIntraday() }}
                  disabled={intradayRefreshing}
                  className="inline-flex items-center justify-center w-5 h-5 rounded text-muted hover:text-accent hover:bg-accent/10 transition-colors disabled:opacity-40"
                  title="刷新分时数据"
                  aria-label="刷新分时数据"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${intradayRefreshing ? 'animate-spin' : ''}`} />
                </button>
              )}
              {/* 自动轮询中: 显示旋转图标提示正在实时刷新 */}
              {intradayChartVisible && intradayAutoRefresh && (
                <RefreshCw className="h-3 w-3 text-accent/60 animate-spin" aria-label="实时刷新中" />
              )}
            </span>
          )
        }
        // 策略列标签展开/收起开关 (命中多策略时行会很高, 默认收起只显首个+计数)
        if (key === 'strategies' && onToggleStrategyTags) {
          return (
            <span className="inline-flex items-center justify-center gap-1.5">
              <span>{col.label}</span>
              <button
                type="button"
                onClick={(event) => { event.stopPropagation(); handleToggleStrategyTags() }}
                className={`inline-flex items-center justify-center w-5 h-5 rounded transition-colors ${
                  strategyTagsExpanded
                    ? 'text-accent bg-accent/10 hover:bg-accent/20'
                    : 'text-muted hover:text-foreground hover:bg-elevated'
                }`}
                title={strategyTagsExpanded ? '收起策略标签（每行仅显示前几个）' : '展开全部策略标签'}
                aria-label={strategyTagsExpanded ? '收起策略标签' : '展开全部策略标签'}
              >
                {strategyTagsExpanded ? <ListTree className="h-3.5 w-3.5" /> : <ListCollapse className="h-3.5 w-3.5" />}
              </button>
            </span>
          )
        }
        return undefined
        }}
      />
      <DimensionMembersDialog
        target={dimensionTarget}
        onClose={() => setDimensionTarget(null)}
        onStockClick={(symbol, name, navList) => {
          setDimensionTarget(null)
          onPreview(symbol, name ?? '', navList)
        }}
      />
    </>
  )
}

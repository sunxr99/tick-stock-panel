import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Flame, Layers3, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { api, type SectorRotationKind, type SectorRotationRow } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'

interface Props {
  kind: SectorRotationKind
}

function score(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '—'
}

function ratio(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(0)}%` : '—'
}

function delta(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}`
}

function deltaTone(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'text-muted'
  return value > 0 ? 'text-bull' : value < 0 ? 'text-bear' : 'text-muted'
}

function dataNote(kind: SectorRotationKind, rows: SectorRotationRow[]) {
  if (kind === 'industry') return '申万三级行业 · 成员关系按申万有效区间解析'
  const asOf = rows[0]?.membership_as_of
  return asOf ? `同花顺概念 · 成员快照 ${asOf}` : '同花顺概念 · 仅展示已保存成员快照的数据'
}

export function SectorRotationBoard({ kind }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const query = useQuery({
    queryKey: QK.sectorRotationLatest(kind, 3),
    queryFn: () => api.sectorRotationLatest(kind, 3),
    staleTime: 5 * 60 * 1000,
  })
  const rows = query.data?.rows ?? []
  const label = kind === 'industry' ? '行业轮动' : '热点轮动'
  const icon = kind === 'industry' ? <Layers3 className="h-4 w-4 text-amber-400" /> : <Flame className="h-4 w-4 text-rose-400" />
  const rising = rows.filter(row => (row.score_delta_5d ?? 0) > 0).length
  const fading = rows.filter(row => (row.score_delta_5d ?? 0) < 0).length
  const partial = rows.filter(row => row.data_status !== 'complete').length
  const selected = rows.find(row => row.sector_id === selectedId) ?? rows[0] ?? null
  const historyQuery = useQuery({
    queryKey: QK.sectorRotationHistory(kind, selected?.sector_id ?? null, 3),
    queryFn: () => api.sectorRotationHistory(kind, selected!.sector_id, 3),
    enabled: Boolean(selected),
    staleTime: 5 * 60 * 1000,
  })

  return (
    <section className="rounded-2xl border border-border bg-surface/90 shadow-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="text-sm font-semibold text-foreground">{label}</h2>
          <span className="text-xs text-muted">{query.data?.row_date ?? '等待盘后计算'}</span>
        </div>
        <span className="text-[11px] text-muted">{dataNote(kind, rows)}</span>
        <button
          type="button"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
          className="ml-auto inline-flex items-center gap-1 text-xs text-muted hover:text-accent disabled:opacity-50"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', query.isFetching && 'animate-spin')} />刷新
        </button>
      </div>

      {query.isLoading ? (
        <div className="flex h-44 items-center justify-center text-sm text-muted"><RefreshCw className="mr-2 h-4 w-4 animate-spin" />读取轮动数据…</div>
      ) : query.isError ? (
        <div className="flex h-44 items-center justify-center gap-2 px-5 text-sm text-bear"><AlertCircle className="h-4 w-4" />轮动数据读取失败，请在盘后同步完成后重试。</div>
      ) : rows.length === 0 ? (
        <div className="flex h-44 flex-col items-center justify-center gap-2 px-5 text-center text-sm text-muted">
          <AlertCircle className="h-5 w-5" />
          <span>{kind === 'concept' ? '尚无当天同花顺概念快照及轮动结果。' : '尚无申万三级行业轮动结果。'}</span>
          <span className="text-xs">完成一次盘后同步后会自动生成；不会使用旧成员关系补造当天数据。</span>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 divide-x divide-border border-b border-border text-center">
            <Metric label="板块数" value={String(rows.length)} />
            <Metric label="5日增强" value={String(rising)} tone="bull" icon={<TrendingUp className="h-3 w-3" />} />
            <Metric label="5日减速" value={String(fading)} tone="bear" icon={<TrendingDown className="h-3 w-3" />} />
          </div>
          {partial > 0 && <div className="border-b border-amber-400/20 bg-amber-400/5 px-4 py-2 text-xs text-amber-500">{partial} 个板块的历史窗口尚不完整，缺失指标显示为“—”，不会被补成分数。</div>}
          <div className="grid gap-4 border-b border-border p-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]">
            <RotationQuadrants rows={rows} selectedId={selected?.sector_id ?? null} onSelect={setSelectedId} />
            <RotationDetail row={selected} rows={historyQuery.data?.rows ?? []} isLoading={historyQuery.isLoading} />
          </div>
          <div className="max-h-[58vh] overflow-auto">
            <table className="w-full min-w-[720px] text-left text-xs">
              <thead className="sticky top-0 z-10 bg-elevated text-muted">
                <tr className="border-b border-border">
                  <th className="w-12 px-4 py-2 font-medium">排名</th>
                  <th className="px-3 py-2 font-medium">板块</th>
                  <th className="px-3 py-2 text-right font-medium">综合强度</th>
                  <th className="px-3 py-2 text-right font-medium">Δ5</th>
                  <th className="px-3 py-2 text-right font-medium">RS20</th>
                  <th className="px-3 py-2 text-right font-medium">上涨广度</th>
                  <th className="px-3 py-2 text-right font-medium">MA20广度</th>
                  <th className="px-3 py-2 text-right font-medium">成交活跃</th>
                  <th className="px-4 py-2 text-right font-medium">数据</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => <RotationRow key={row.sector_id} row={row} rank={index + 1} selected={row.sector_id === selected?.sector_id} onSelect={setSelectedId} />)}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}

function Metric({ label, value, tone, icon }: { label: string; value: string; tone?: 'bull' | 'bear'; icon?: ReactNode }) {
  return <div className="px-3 py-2.5"><div className="text-[11px] text-muted">{label}</div><div className={cn('mt-0.5 flex items-center justify-center gap-1 text-sm font-semibold tabular-nums', tone === 'bull' && 'text-bull', tone === 'bear' && 'text-bear')}>{icon}{value}</div></div>
}

function RotationRow({ row, rank, selected, onSelect }: { row: SectorRotationRow; rank: number; selected: boolean; onSelect: (id: string) => void }) {
  return (
    <tr onClick={() => onSelect(row.sector_id)} className={cn('cursor-pointer border-b border-border/60 transition-colors hover:bg-elevated/60', selected && 'bg-accent/10')}>
      <td className="px-4 py-2.5 text-muted tabular-nums">{rank}</td>
      <td className="px-3 py-2.5"><div className="font-medium text-foreground">{row.name}</div><div className="mt-0.5 text-[10px] text-muted">{row.valid_member_count}/{row.member_count} 只有效成员</div></td>
      <td className="px-3 py-2.5 text-right font-medium tabular-nums text-foreground">{score(row.sector_score)}</td>
      <td className={cn('px-3 py-2.5 text-right font-medium tabular-nums', deltaTone(row.score_delta_5d))}>{delta(row.score_delta_5d)}</td>
      <td className="px-3 py-2.5 text-right tabular-nums">{score(row.rs20_score)}</td>
      <td className="px-3 py-2.5 text-right tabular-nums">{ratio(row.up_ratio)}</td>
      <td className="px-3 py-2.5 text-right tabular-nums">{ratio(row.breadth_ma20)}</td>
      <td className="px-3 py-2.5 text-right tabular-nums">{score(row.amount_ratio)}</td>
      <td className={cn('px-4 py-2.5 text-right text-[11px]', row.data_status === 'complete' ? 'text-muted' : 'text-amber-500')}>{row.data_status === 'complete' ? '完整' : '部分'}</td>
    </tr>
  )
}

function RotationQuadrants({ rows, selectedId, onSelect }: { rows: SectorRotationRow[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const points = rows.filter(row => row.score_delta_5d != null && row.rs20_score != null)
  const maxDelta = Math.max(5, ...points.map(row => Math.abs(row.score_delta_5d!)))
  const chartWidth = 620
  const chartHeight = 250
  const padding = 26
  const x = (value: number) => padding + ((value + maxDelta) / (maxDelta * 2)) * (chartWidth - padding * 2)
  const y = (value: number) => chartHeight - padding - (Math.max(0, Math.min(100, value)) / 100) * (chartHeight - padding * 2)
  return <div>
    <div className="mb-1 flex items-baseline justify-between"><div><h3 className="text-sm font-semibold text-foreground">四象限雷达</h3><p className="mt-0.5 text-[11px] text-muted">横轴为 5 日综合强度变化，纵轴为 RS20 横截面强度；点击点或榜单查看详情。</p></div><span className="text-[11px] text-muted">{points.length}/{rows.length} 可定位</span></div>
    <div className="overflow-hidden rounded-xl border border-border bg-elevated/35 p-2">
      <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="h-[230px] w-full" role="img" aria-label="行业或概念轮动四象限图">
        <rect x={padding} y={padding} width={chartWidth - padding * 2} height={chartHeight - padding * 2} fill="transparent" stroke="currentColor" className="text-border" />
        <line x1={x(0)} x2={x(0)} y1={padding} y2={chartHeight - padding} className="stroke-border" strokeDasharray="4 4" />
        <line x1={padding} x2={chartWidth - padding} y1={y(50)} y2={y(50)} className="stroke-border" strokeDasharray="4 4" />
        <text x={padding + 7} y={padding + 15} className="fill-muted text-[11px]">强势但减速</text>
        <text x={chartWidth - padding - 69} y={padding + 15} className="fill-muted text-[11px]">强势且增强</text>
        <text x={padding + 7} y={chartHeight - padding - 7} className="fill-muted text-[11px]">弱势且减速</text>
        <text x={chartWidth - padding - 69} y={chartHeight - padding - 7} className="fill-muted text-[11px]">弱势但修复</text>
        <text x={padding} y={chartHeight - 4} className="fill-muted text-[10px]">减速</text><text x={chartWidth - padding - 20} y={chartHeight - 4} className="fill-muted text-[10px]">增强</text>
        {points.map(row => <circle key={row.sector_id} cx={x(row.score_delta_5d!)} cy={y(row.rs20_score!)} r={row.sector_id === selectedId ? 7 : 4.5} onClick={() => onSelect(row.sector_id)} className={cn('cursor-pointer transition-all', row.data_status === 'complete' ? 'fill-accent' : 'fill-amber-400', row.sector_id === selectedId && 'stroke-foreground stroke-2')}><title>{`${row.name} · RS20 ${score(row.rs20_score)} · Δ5 ${delta(row.score_delta_5d)}`}</title></circle>)}
      </svg>
    </div>
  </div>
}

function RotationDetail({ row, rows, isLoading }: { row: SectorRotationRow | null; rows: SectorRotationRow[]; isLoading: boolean }) {
  const trend = useMemo(() => [...rows].sort((a, b) => a.date.localeCompare(b.date)).filter(item => item.sector_score != null), [rows])
  const line = useMemo(() => {
    if (trend.length < 2) return null
    const values = trend.map(item => item.sector_score!)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const span = max - min || 1
    return values.map((value, index) => `${(index / (values.length - 1)) * 100},${42 - ((value - min) / span) * 38}`).join(' ')
  }, [trend])
  if (!row) return null
  return <div className="rounded-xl border border-border bg-surface/70 p-3"><div className="flex items-start justify-between gap-3"><div><h3 className="text-sm font-semibold text-foreground">{row.name}</h3><p className="mt-0.5 text-[11px] text-muted">{row.data_status === 'complete' ? '指标窗口完整' : '历史窗口部分缺失'} · 点击榜单可切换</p></div><span className="rounded-md bg-accent/10 px-2 py-1 text-xs font-semibold text-accent">{score(row.sector_score)}</span></div>
    <div className="mt-3 grid grid-cols-4 gap-2 text-center"><DetailMetric label="RS20" value={score(row.rs20_score)} /><DetailMetric label="趋势" value={score(row.trend_score)} /><DetailMetric label="广度" value={score(row.breadth_score)} /><DetailMetric label="活跃" value={score(row.volume_score)} /></div>
    <div className="mt-3 rounded-lg bg-elevated/60 px-2 py-1.5"><div className="flex justify-between text-[10px] text-muted"><span>综合强度历史</span><span>{isLoading ? '读取中…' : trend.length >= 2 ? `${trend.length} 日` : '数据积累中'}</span></div>{line ? <svg viewBox="0 0 100 46" preserveAspectRatio="none" className="mt-1 h-12 w-full"><polyline points={line} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" className="text-accent" /></svg> : <div className="flex h-12 items-center justify-center text-[11px] text-muted">至少累计两日后展示趋势</div>}</div>
    <div className="mt-2 flex justify-between text-[11px] text-muted"><span>5 日变化 <span className={deltaTone(row.score_delta_5d)}>{delta(row.score_delta_5d)}</span></span><span>上涨广度 {ratio(row.up_ratio)}</span></div>
  </div>
}

function DetailMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-elevated/60 px-1 py-1.5"><div className="text-[10px] text-muted">{label}</div><div className="mt-0.5 text-xs font-medium tabular-nums text-foreground">{value}</div></div>
}

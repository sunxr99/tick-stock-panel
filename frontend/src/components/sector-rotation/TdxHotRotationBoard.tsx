import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Layers3, RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api, type MarketSnapshotRow, type TdxHotRotationMember, type TdxHotRotationRow } from '@/lib/api'
import { cn } from '@/lib/cn'
import { fmtBigNum, fmtPct, fmtPrice, priceColorClass } from '@/lib/format'
import { QK } from '@/lib/queryKeys'

type DisplayCategory = 'concept' | 'industry' | 'style' | 'all'

const CATEGORIES: Array<{ value: DisplayCategory; label: string }> = [
  { value: 'concept', label: '概念板块' },
  { value: 'industry', label: '行业板块' },
  { value: 'style', label: '风格板块' },
  { value: 'all', label: '全部' },
]

function pct(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '—'
}

function tone(value: number | null | undefined) {
  return typeof value !== 'number' || !Number.isFinite(value) ? 'text-muted' : value > 0 ? 'text-bull' : value < 0 ? 'text-bear' : 'text-muted'
}

function withPercentile(rows: TdxHotRotationRow[]) {
  const ranked = rows.filter(row => typeof row.return_5d === 'number' && Number.isFinite(row.return_5d)).sort((a, b) => a.return_5d! - b.return_5d!)
  if (ranked.length < 2) return rows
  const fallback = new Map<string, number>()
  for (let start = 0; start < ranked.length;) {
    let end = start
    while (end + 1 < ranked.length && ranked[end + 1].return_5d === ranked[start].return_5d) end += 1
    const percentile = ((start + end) / 2 / (ranked.length - 1)) * 100
    for (let index = start; index <= end; index += 1) fallback.set(ranked[index].ts_code, percentile)
    start = end + 1
  }
  return rows.map(row => typeof row.return_5d_percentile === 'number' ? row : { ...row, return_5d_percentile: fallback.get(row.ts_code) ?? null })
}

export function TdxHotRotationBoard() {
  const [category, setCategory] = useState<DisplayCategory>('concept')
  const [selectedCode, setSelectedCode] = useState<string | null>(null)
  const latestQuery = useQuery({ queryKey: QK.tdxHotRotationLatest(category), queryFn: () => api.tdxHotRotationLatest(category), staleTime: 5 * 60 * 1000 })
  const rows = useMemo(() => withPercentile(latestQuery.data?.rows ?? []), [latestQuery.data?.rows])
  const selected = rows.find(row => row.ts_code === selectedCode) ?? rows[0] ?? null
  const historyQuery = useQuery({ queryKey: QK.tdxHotRotationHistory(selected?.ts_code ?? null), queryFn: () => api.tdxHotRotationHistory(selected!.ts_code), enabled: Boolean(selected), staleTime: 5 * 60 * 1000 })
  const membersQuery = useQuery({ queryKey: QK.tdxHotRotationMembers(selected?.ts_code ?? null, selected?.date ?? null), queryFn: () => api.tdxHotRotationMembers(selected!.ts_code, selected!.date), enabled: Boolean(selected), staleTime: 5 * 60 * 1000 })
  const marketQuery = useQuery({ queryKey: QK.marketSnapshot, queryFn: api.marketSnapshot, enabled: Boolean(selected), staleTime: 30 * 1000 })
  const advancing = rows.filter(row => (row.pct_change ?? 0) > 0).length
  const declining = rows.filter(row => (row.pct_change ?? 0) < 0).length

  return <section className="rounded-2xl border border-border bg-surface/90 shadow-sm">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-3">
      <div className="flex items-center gap-2"><Layers3 className="h-4 w-4 text-cyan-400" /><h2 className="text-sm font-semibold text-foreground">通达信热点轮动</h2><span className="text-xs text-muted">{latestQuery.data?.row_date ?? '等待下载完成'}</span></div>
      <span className="text-[11px] text-muted">88xxxx.TDX 原始板块行情 · 平铺分类</span>
      <div className="flex rounded-lg border border-border bg-elevated/40 p-0.5">{CATEGORIES.map(option => <button key={option.value} type="button" onClick={() => { setCategory(option.value); setSelectedCode(null) }} className={cn('rounded-md px-2 py-1 text-[11px] transition-colors', category === option.value ? 'bg-accent text-white' : 'text-muted hover:text-foreground')}>{option.label}</button>)}</div>
      <button type="button" onClick={() => latestQuery.refetch()} disabled={latestQuery.isFetching} className="ml-auto inline-flex items-center gap-1 text-xs text-muted hover:text-accent disabled:opacity-50"><RefreshCw className={cn('h-3.5 w-3.5', latestQuery.isFetching && 'animate-spin')} />刷新</button>
    </div>
    {latestQuery.isLoading ? <Loading /> : latestQuery.isError ? <ErrorState /> : rows.length === 0 ? <Empty category={category} /> : <>
      <div className="grid grid-cols-3 divide-x divide-border border-b border-border text-center"><Metric label="板块" value={String(rows.length)} /><Metric label="上涨" value={String(advancing)} tone="bull" /><Metric label="下跌" value={String(declining)} tone="bear" /></div>
      <div className="grid gap-4 border-b border-border p-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]"><Quadrants rows={rows} selectedCode={selected?.ts_code ?? null} onSelect={setSelectedCode} /><BoardDetail row={selected} history={historyQuery.data?.rows ?? []} historyLoading={historyQuery.isLoading} members={membersQuery.data?.rows ?? []} membersTotal={membersQuery.data?.total ?? 0} membersLoading={membersQuery.isLoading} membersError={membersQuery.isError} marketRows={marketQuery.data?.rows ?? []} /></div>
      <div className="max-h-[58vh] overflow-auto"><table className="w-full min-w-[720px] text-left text-xs"><thead className="sticky top-0 z-10 bg-elevated text-muted"><tr className="border-b border-border"><th className="w-12 px-4 py-2 font-medium">排名</th><th className="px-3 py-2 font-medium">板块</th><th className="px-3 py-2 text-right font-medium">当日涨跌</th><th className="px-3 py-2 text-right font-medium">5 日累计</th><th className="px-3 py-2 text-right font-medium">换手率</th><th className="px-3 py-2 text-right font-medium">上涨/下跌</th><th className="px-4 py-2 text-right font-medium">成交额</th></tr></thead><tbody>{rows.map((row, index) => <tr key={row.ts_code} onClick={() => setSelectedCode(row.ts_code)} className={cn('cursor-pointer border-b border-border/60 transition-colors hover:bg-elevated/60', row.ts_code === selected?.ts_code && 'bg-accent/10')}><td className="px-4 py-2.5 text-muted tabular-nums">{index + 1}</td><td className="px-3 py-2.5"><div className="font-medium text-foreground">{row.name}</div><div className="mt-0.5 text-[10px] text-muted">{row.idx_type} · <span className="font-mono">{row.ts_code}</span></div></td><td className={cn('px-3 py-2.5 text-right font-mono font-medium tabular-nums', tone(row.pct_change))}>{pct(row.pct_change)}</td><td className={cn('px-3 py-2.5 text-right font-mono tabular-nums', tone(row.return_5d))}>{pct(row.return_5d)}</td><td className="px-3 py-2.5 text-right font-mono tabular-nums">{pct(row.turnover_rate)}</td><td className="px-3 py-2.5 text-right tabular-nums"><span className="text-bull">{row.up_num ?? '—'}</span><span className="px-1 text-muted">/</span><span className="text-bear">{row.down_num ?? '—'}</span></td><td className="px-4 py-2.5 text-right font-mono tabular-nums text-muted">{fmtBigNum(row.amount)}</td></tr>)}</tbody></table></div>
    </>}
  </section>
}

function Loading() { return <div className="flex h-44 items-center justify-center text-sm text-muted"><RefreshCw className="mr-2 h-4 w-4 animate-spin" />读取通达信板块数据…</div> }
function ErrorState() { return <div className="flex h-44 items-center justify-center gap-2 px-5 text-sm text-bear"><AlertCircle className="h-4 w-4" />通达信热点数据读取失败。</div> }
function Empty({ category }: { category: DisplayCategory }) { return <div className="flex h-44 items-center justify-center px-5 text-center text-sm text-muted">{category === 'all' ? '通达信板块数据尚未完成下载。' : `暂无通达信${CATEGORIES.find(item => item.value === category)?.label ?? ''}数据。`}</div> }
function Metric({ label, value, tone: metricTone }: { label: string; value: string; tone?: 'bull' | 'bear' }) { return <div className="px-3 py-2.5"><div className="text-[11px] text-muted">{label}</div><div className={cn('mt-0.5 text-sm font-semibold tabular-nums', metricTone === 'bull' && 'text-bull', metricTone === 'bear' && 'text-bear')}>{value}</div></div> }

function Quadrants({ rows, selectedCode, onSelect }: { rows: TdxHotRotationRow[]; selectedCode: string | null; onSelect: (code: string) => void }) {
  const points = rows.filter(row => row.pct_change != null && row.return_5d_percentile != null)
  const maxChange = Math.max(5, ...points.map(row => Math.abs(row.pct_change!)))
  const width = 620; const height = 250; const padding = 26
  const x = (value: number) => padding + ((value + maxChange) / (maxChange * 2)) * (width - padding * 2)
  const y = (value: number) => height - padding - (Math.max(0, Math.min(100, value)) / 100) * (height - padding * 2)
  return <div><div className="mb-1 flex items-baseline justify-between"><div><h3 className="text-sm font-semibold text-foreground">原始动量四象限</h3><p className="mt-0.5 text-[11px] text-muted">横轴：当日涨跌幅；纵轴：5 日累计涨幅的当日横截面百分位。</p></div><span className="text-[11px] text-muted">{points.length}/{rows.length} 可定位</span></div><div className="overflow-hidden rounded-xl border border-border bg-elevated/35 p-2"><svg viewBox={`0 0 ${width} ${height}`} className="h-[230px] w-full" role="img" aria-label="通达信板块原始动量四象限图"><rect x={padding} y={padding} width={width - padding * 2} height={height - padding * 2} fill="transparent" stroke="currentColor" className="text-border" /><line x1={x(0)} x2={x(0)} y1={padding} y2={height - padding} className="stroke-border" strokeDasharray="4 4" /><line x1={padding} x2={width - padding} y1={y(50)} y2={y(50)} className="stroke-border" strokeDasharray="4 4" /><text x={padding + 7} y={padding + 15} className="fill-muted text-[11px]">强势但回落</text><text x={width - padding - 69} y={padding + 15} className="fill-muted text-[11px]">强势且加速</text><text x={padding + 7} y={height - padding - 7} className="fill-muted text-[11px]">弱势且走弱</text><text x={width - padding - 69} y={height - padding - 7} className="fill-muted text-[11px]">弱势修复</text>{points.map(row => <circle key={row.ts_code} cx={x(row.pct_change!)} cy={y(row.return_5d_percentile!)} r={row.ts_code === selectedCode ? 7 : 4.5} onClick={() => onSelect(row.ts_code)} className={cn('cursor-pointer transition-all', tone(row.pct_change) === 'text-bull' ? 'fill-rose-400' : tone(row.pct_change) === 'text-bear' ? 'fill-emerald-400' : 'fill-muted', row.ts_code === selectedCode && 'stroke-foreground stroke-2')}><title>{`${row.name} · 当日 ${pct(row.pct_change)} · 5日强度 ${row.return_5d_percentile!.toFixed(0)}%`}</title></circle>)}</svg></div></div>
}

function BoardDetail({ row, history, historyLoading, members, membersTotal, membersLoading, membersError, marketRows }: { row: TdxHotRotationRow | null; history: TdxHotRotationRow[]; historyLoading: boolean; members: TdxHotRotationMember[]; membersTotal: number; membersLoading: boolean; membersError: boolean; marketRows: MarketSnapshotRow[] }) {
  const values = history.map(item => item.pct_change).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const line = useMemo(() => { if (values.length < 2) return null; const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1; return values.map((value, index) => `${(index / (values.length - 1)) * 100},${42 - ((value - min) / span) * 38}`).join(' ') }, [values])
  if (!row) return null
  return <div className="rounded-xl border border-border bg-surface/70 p-3"><div className="flex items-start justify-between gap-3"><div><h3 className="text-sm font-semibold text-foreground">{row.name}</h3><p className="mt-0.5 text-[11px] text-muted">{row.idx_type} · {row.ts_code}</p></div><span className={cn('rounded-md bg-elevated px-2 py-1 font-mono text-xs font-semibold', tone(row.pct_change))}>{pct(row.pct_change)}</span></div><div className="mt-3 grid grid-cols-3 gap-2 text-center"><Detail label="5日累计" value={pct(row.return_5d)} toneValue={row.return_5d} /><Detail label="收盘" value={fmtPrice(row.close)} /><Detail label="成交额" value={fmtBigNum(row.amount)} /></div><div className="mt-3 rounded-lg bg-elevated/60 px-2 py-1.5"><div className="flex justify-between text-[10px] text-muted"><span>当日涨跌历史</span><span>{historyLoading ? '读取中…' : `${history.length} 个交易日`}</span></div>{line ? <svg viewBox="0 0 100 46" preserveAspectRatio="none" className="mt-1 h-12 w-full"><polyline points={line} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" className="text-accent" /></svg> : <div className="flex h-12 items-center justify-center text-[11px] text-muted">数据积累中</div>}</div><Members row={row} members={members} total={membersTotal} loading={membersLoading} error={membersError} marketRows={marketRows} /></div>
}
function Detail({ label, value, toneValue }: { label: string; value: string; toneValue?: number | null }) { return <div className="rounded-lg bg-elevated/60 px-1 py-1.5"><div className="text-[10px] text-muted">{label}</div><div className={cn('mt-0.5 text-xs font-medium tabular-nums', toneValue == null ? 'text-foreground' : tone(toneValue))}>{value}</div></div> }
function normalizedCode(code: string) { return code.trim().toUpperCase().replace(/\.(SH|SZ|BJ)$/, '') }
function Members({ row, members, total, loading, error, marketRows }: { row: TdxHotRotationRow; members: TdxHotRotationMember[]; total: number; loading: boolean; error: boolean; marketRows: MarketSnapshotRow[] }) {
  const quotes = useMemo(() => new Map(marketRows.map(item => [normalizedCode(item.symbol), item])), [marketRows])
  return <div className="mt-3 border-t border-border pt-3"><div className="flex items-baseline justify-between gap-2"><div><h4 className="text-xs font-semibold text-foreground">成分股</h4><p className="mt-0.5 text-[10px] text-muted">成员关系：{row.date} 通达信快照；行情：最新市场快照</p></div><span className="text-[11px] tabular-nums text-muted">{loading ? '读取中…' : `${total} 只`}</span></div>{loading ? <div className="flex h-24 items-center justify-center text-xs text-muted"><RefreshCw className="mr-1.5 h-3.5 w-3.5 animate-spin" />读取当日成分股…</div> : error ? <div className="flex h-16 items-center justify-center text-xs text-bear">成分股读取失败</div> : members.length === 0 ? <div className="flex h-16 items-center justify-center text-xs text-muted">该日期暂无可用成分股快照</div> : <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-border"><table className="w-full min-w-[420px] text-left text-[11px]"><thead className="sticky top-0 z-10 bg-elevated text-muted"><tr><th className="px-2 py-1.5 font-medium">代码</th><th className="px-2 py-1.5 font-medium">名称</th><th className="px-2 py-1.5 text-right font-medium">最新涨跌</th><th className="px-2 py-1.5 text-right font-medium">最新价</th><th className="px-2 py-1.5 text-right font-medium">成交额</th></tr></thead><tbody>{members.map(member => { const quote = quotes.get(normalizedCode(member.con_code)); return <tr key={member.con_code} className="border-t border-border/60"><td className="px-2 py-1.5 font-mono text-muted">{member.con_code}</td><td className="px-2 py-1.5 font-medium text-foreground">{quote?.name || member.con_name || '—'}</td><td className={cn('px-2 py-1.5 text-right font-mono tabular-nums', priceColorClass(quote?.change_pct))}>{fmtPct(quote?.change_pct)}</td><td className="px-2 py-1.5 text-right font-mono tabular-nums text-foreground">{fmtPrice(quote?.close)}</td><td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted">{fmtBigNum(quote?.amount)}</td></tr> })}</tbody></table></div>}</div>
}

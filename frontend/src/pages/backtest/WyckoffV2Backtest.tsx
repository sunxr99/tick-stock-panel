import { useMutation, useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

const ENTRIES = [
  ['spring_aggressive', 'Aggressive Spring'],
  ['spring_standard', 'Standard Spring'],
  ['spring_conservative', 'Conservative Spring'],
  ['lps_classic_standard', 'Classic LPS'],
  ['lps_shallow_standard', 'Shallow LPS'],
] as const

const EXPERIMENTS = [
  ['SPRING_BASE', 'Spring baseline'], ['SPRING_TEST_VALID', 'Supply Test'],
  ['SPRING_CONFIRM_BASE', 'Demand base'], ['SPRING_CONFIRM_ATR', 'Demand + ATR'],
  ['SPRING_CONFIRM_CLV', 'Demand + CLV'], ['SPRING_CONFIRM_VOLUME', 'Demand + Volume'],
  ['SPRING_CONFIRM_CLV_VOLUME', 'Demand + CLV + Volume'], ['SPRING_CONFIRM_SWING_HIGH', 'Demand + Swing High'],
  ['LPS_CLASSIC_BASE', 'Classic LPS'], ['LPS_CLASSIC_SWING_CONFIRM', 'Classic + Swing High'],
  ['LPS_CLASSIC_SOS_HELD_20', 'Classic + SOS held 20%'], ['LPS_CLASSIC_SOS_HELD_30', 'Classic + SOS held 30%'],
  ['LPS_CLASSIC_SOS_HELD_40', 'Classic + SOS held 40%'], ['LPS_CLASSIC_SOS_HELD_50', 'Classic + SOS held 50%'],
  ['LPS_SHALLOW_BASE', 'Shallow LPS'],
] as const

export function WyckoffV2Backtest() {
  const [startDate, setStartDate] = useState('2023-01-01')
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10))
  const [entries, setEntries] = useState<string[]>(ENTRIES.map(([key]) => key))
  const [experiments, setExperiments] = useState<string[]>([])
  const [benchmark, setBenchmark] = useState<'all_a' | '000300.SH' | 'none'>('all_a')
  const [forceRecompute, setForceRecompute] = useState(false)
  const [runId, setRunId] = useState<string | null>(null)
  const [showEvents, setShowEvents] = useState(false)
  const run = useMutation({
    mutationFn: () => api.wyckoffV2Run({ start_date: startDate, end_date: endDate, entries, experiment_variants: experiments, benchmark, horizons: Array.from({ length: 30 }, (_, index) => index + 1), force_recompute: forceRecompute }),
    onSuccess: result => setRunId(result.run_id),
  })
  const status = useQuery({ queryKey: QK.wyckoffV2Run(runId ?? ''), queryFn: () => api.wyckoffV2Status(runId!), enabled: Boolean(runId), refetchInterval: query => query.state.data?.status === 'RUNNING' || query.state.data?.status === 'QUEUED' ? 1000 : false })
  const summary = useQuery({ queryKey: QK.wyckoffV2Summary(runId ?? ''), queryFn: () => api.wyckoffV2Summary(runId!), enabled: status.data?.status === 'SUCCESS' })
  const events = useQuery({ queryKey: QK.wyckoffV2Events(runId ?? '', 0, 100), queryFn: () => api.wyckoffV2Events(runId!), enabled: showEvents && status.data?.status === 'SUCCESS' })
  const rows = useMemo(() => Object.entries((summary.data?.entries as Record<string, any> | undefined) ?? {}), [summary.data])
  const toggle = (key: string) => setEntries(current => current.includes(key) ? current.filter(value => value !== key) : [...current, key])
  const toggleExperiment = (key: string) => setExperiments(current => current.includes(key) ? current.filter(value => value !== key) : [...current, key])

  return <section className="mx-auto max-w-7xl space-y-4">
    <div className="rounded-card border border-accent/30 bg-accent/5 p-3 text-sm text-secondary">Wyckoff V2 研究回测，不影响正式选股结果。成交口径：信号确认后下一交易日开盘买入，T+N 收盘评估。</div>
    <div className="grid gap-3 rounded-card border border-border bg-surface p-4 md:grid-cols-4">
      <label className="text-sm">开始日期<input className="mt-1 w-full rounded border border-border bg-base p-2" type="date" value={startDate} onChange={event => setStartDate(event.target.value)} /></label>
      <label className="text-sm">结束日期<input className="mt-1 w-full rounded border border-border bg-base p-2" type="date" value={endDate} onChange={event => setEndDate(event.target.value)} /></label>
      <label className="text-sm">基准<select className="mt-1 w-full rounded border border-border bg-base p-2" value={benchmark} onChange={event => setBenchmark(event.target.value as typeof benchmark)}><option value="all_a">全 A（沪深300代理）</option><option value="000300.SH">沪深300</option><option value="none">不比较基准</option></select></label>
      <div className="flex items-end gap-3"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={forceRecompute} onChange={event => setForceRecompute(event.target.checked)} />强制重算</label><button className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={!entries.length || run.isPending} onClick={() => run.mutate()}>{run.isPending ? '提交中…' : '开始回测'}</button></div>
      <fieldset className="md:col-span-4"><legend className="mb-1 text-sm">Entry</legend><div className="flex flex-wrap gap-4">{ENTRIES.map(([key, label]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={entries.includes(key)} onChange={() => toggle(key)} />{label}</label>)}</div></fieldset>
      <fieldset className="md:col-span-4"><legend className="mb-1 text-sm">Experiment Matrix（多选仅作横向研究，不会自动挑选最优）</legend><div className="flex flex-wrap gap-4">{EXPERIMENTS.map(([key, label]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={experiments.includes(key)} onChange={() => toggleExperiment(key)} />{label}</label>)}</div></fieldset>
    </div>
    {status.data && <div className="rounded-card border border-border bg-surface p-3 text-sm">状态：{status.data.status}　进度：{status.data.progress?.processed_symbols ?? 0}/{status.data.progress?.total_symbols ?? 0}（{status.data.progress?.percent ?? 0}%）　耗时：{Math.round(status.data.elapsed_seconds ?? 0)} 秒 {status.data.error && <span className="text-red-500">{status.data.error}</span>}</div>}
    {rows.length > 0 && <div className="overflow-x-auto rounded-card border border-border bg-surface p-3"><table className="min-w-full text-left text-xs"><thead><tr><th>Entry</th><th>样本</th><th>Unique Stocks</th><th>Unique Ranges</th>{[1, 3, 5, 10, 20].map(day => <th key={day}>T+{day}<br />均值 / 中位 / 胜率 / 超额</th>)}<th>Median MFE / MAE</th><th>Profit Factor</th></tr></thead><tbody>{rows.map(([entry, result]) => { const horizons = result.horizons as Record<string, any>; const first = horizons['1']; return <tr key={entry} className="border-t border-border"><td>{entry}</td><td>{result.events}</td><td>{first?.unique_symbols ?? '-'}</td><td>{first?.unique_ranges ?? '-'}</td>{[1, 3, 5, 10, 20].map(day => { const metric = horizons[String(day)]; return <td key={day}>{metric?.mean_return_pct ?? '-'}% / {metric?.median_return_pct ?? '-'}% / {metric?.positive_return_rate == null ? '-' : `${(metric.positive_return_rate * 100).toFixed(1)}%`} / {metric?.mean_excess_return_pct ?? '-'}%</td> })}<td>{first?.median_mfe_pct ?? '-'}% / {first?.median_mae_pct ?? '-'}%</td><td>{first?.profit_factor ?? '-'}</td></tr>})}</tbody></table></div>}
    {Boolean(summary.data?.spring_outcomes) && <div className="rounded-card border border-border bg-surface p-3 text-sm"><div className="mb-2 font-medium">Spring 后续状态（不是单一“失败率”）</div>{Object.entries((summary.data?.spring_outcomes as any).rates).map(([name, value]) => <span key={name} className="mr-4">{name}: {(Number(value) * 100).toFixed(1)}%</span>)}</div>}
    {Boolean(summary.data?.lps_funnel) && <div className="rounded-card border border-border bg-surface p-3 text-sm"><div className="mb-2 font-medium">LPS 漏斗与拒绝原因</div><div className="flex flex-wrap gap-4">{Object.entries(summary.data?.lps_funnel as Record<string, any>).map(([name, value]) => <span key={name}>{name}: {value.count}（{(Number(value.conversion_rate) * 100).toFixed(2)}%）</span>)}</div>{Object.entries((summary.data?.lps_rejection_reasons as Record<string, any>) ?? {}).map(([name, value]) => <span className="mr-4 text-secondary" key={name}>{name}: {String((value as any).count)}</span>)}</div>}
    {status.data?.status === 'SUCCESS' && <div className="flex gap-3"><button className="rounded-btn border border-border px-3 py-2 text-sm" onClick={() => setShowEvents(value => !value)}>{showEvents ? '隐藏事件' : '查看事件'}</button><a className="rounded-btn border border-border px-3 py-2 text-sm" href={api.wyckoffV2ExportUrl(runId!)}>导出 CSV</a><a className="rounded-btn border border-border px-3 py-2 text-sm" href={api.wyckoffV2ReportUrl(runId!)}>下载 report.md</a></div>}
    {showEvents && events.data && <div className="overflow-x-auto rounded-card border border-border bg-surface p-3"><table className="min-w-full text-left text-xs"><thead><tr><th>股票</th><th>日期</th><th>Entry</th><th>Range</th><th>状态</th><th>T+5</th><th>MFE</th><th>MAE</th></tr></thead><tbody>{events.data.items.map((item, index) => { const outcomes = item.outcomes as Record<string, any>; return <tr className="border-t border-border" key={`${String(item.event_id)}-${index}`}><td>{String(item.symbol)}</td><td>{String(item.date)}</td><td>{String(item.entry)}</td><td>{String(item.range_id)}</td><td>{String(item.state)}</td><td>{outcomes['5']?.return_pct ?? '-'}</td><td>{outcomes['5']?.mfe_pct ?? '-'}</td><td>{outcomes['5']?.mae_pct ?? '-'}</td></tr> })}</tbody></table></div>}
  </section>
}

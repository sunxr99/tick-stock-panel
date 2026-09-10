import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import type { ECharts, EChartsOption } from 'echarts'
import { api } from '@/lib/api'
import { useChartTheme } from '@/lib/theme'
import type { FrontendExtension, FrontendSlotRegistration } from '@/extensions/types'

type TimeframeState = {
  timeframe: string
  direction: 'BULLISH' | 'BEARISH' | 'UNKNOWN'
  structure_state: string
  as_of: string
  native_state: { raw_value: string; values: { v1: string; v2: string; v3: string; score: number } }
  latest_bi: { sdt: string; edt: string; direction: string } | null
  latest_fx: { dt: string; mark: string; price: number; high: number; low: number; power: string } | null
  latest_center: { sdt: string; edt: string; zg: number; zd: number; gg: number; dd: number } | null
  quality: { id: string; label: string; raw_signal: string; raw_value: string; values: { v1: string; v2: string; v3: string; score: number } }[]
}

type ResonanceResult = {
  resonance_type: string
  direction: 'BULLISH' | 'BEARISH' | 'UNKNOWN'
  resonance_time: string | null
  timeframe_states: Record<string, TimeframeState>
  evidence: { code: string; timeframe: string; direction: string; structure_state: string; confirmation_time: string }[]
  warnings: { code: string }[]
  summary: string
  current_only: boolean
  event: { time: string; resonance_type: string; direction: string; summary: string; evidence: { code: string; timeframe: string; direction: string; structure_state: string; confirmation_time: string }[]; warnings: { code: string }[] } | null
}

type TimeframeAnalysis = {
  timeframe: string
  source: string
  state: TimeframeState
  bars: { dt: string; open: number; high: number; low: number; close: number; vol: number }[]
  bi: {
    sdt: string
    edt: string
    event_time: string
    confirmation_time: string | null
    status: 'confirmed'
    direction: string
    start_price: number
    end_price: number
    high: number
    low: number
    power: number
  }[]
  zs: { sdt: string; edt: string; event_time: string; confirmation_time: string | null; status: 'confirmed'; zg: number; zd: number; gg: number; dd: number }[]
  buy_sell: {
    dt: string; event_time: string; confirmation_time: string; type: string; price: number; status: 'confirmed'
    structure_anchor: { sdt: string; edt: string; direction: string } | null
    signal: {
      signal_name: string; signal_key: string; raw_signal: string; raw_value: string
      values: { v1: string; v2: string; v3: string; score: number }
      parameters: Record<string, string | number>; structure_count: string | null; subcondition: string | null
    }
    higher_timeframe_context: {
      summary: '顺高周期结构' | '逆高周期结构' | '高周期冲突' | '上下文不明确'
      timeframes: { timeframe: string; values: { v1: string; v2: string; v3: string; score: number }; raw_signal: string }[]
    }
  }[]
}

type AnalyzeResponse = TimeframeAnalysis & {
  symbol: string
  asset_type: string
  bars_count: number
  bi_count: number
  zs_count: number
  buy_sell_count: number
  timeframes: Record<string, TimeframeAnalysis>
  multi_timeframe_summary: { timeframe: string; bars_count: number; bi_count: number; zs_count: number; signal_count: number; source: string }[]
  base_frequency: string
  minute_data_available: boolean
  resonance: ResonanceResult
}

const BULL = '#C74040'
const BEAR = '#2D9B65'
const BI_COLOR = '#F59E0B'
const ZS_COLOR = 'rgba(59,130,246,0.10)'

const TYPE_META: Record<string, { label: string; buy: boolean }> = {
  一买: { label: 'B1', buy: true },
  二买: { label: 'B2', buy: true },
  三买: { label: 'B3', buy: true },
  一卖: { label: 'S1', buy: false },
  二卖: { label: 'S2', buy: false },
  三卖: { label: 'S3', buy: false },
}

function signalTooltip(point: TimeframeAnalysis['buy_sell'][number]): string {
  const context = point.higher_timeframe_context
  const params = Object.entries(point.signal.parameters).map(([key, value]) => `${key}=${value}`).join(', ') || '无'
  const higher = context.timeframes.map((item) => `${item.timeframe}: ${item.values.v1} · ${item.values.v2}`).join('<br/>') || '暂无可用高周期原生状态'
  const anchor = point.structure_anchor ? `${point.structure_anchor.sdt} → ${point.structure_anchor.edt}（${point.structure_anchor.direction}笔）` : 'CZSC 未提供笔锚点'
  return `<b>${point.type} · ${context.summary}</b><br/>CZSC: ${point.signal.signal_name}<br/>原始值: ${point.signal.raw_value}<br/>参数: ${params}<br/>结构锚点: ${anchor}<br/>结构时间: ${point.event_time}<br/>确认时间: ${point.confirmation_time}<br/>高周期状态:<br/>${higher}`
}

function resonanceTooltip(event: NonNullable<ResonanceResult['event']>): string {
  const evidence = event.evidence.map((item) => `${item.timeframe}: ${item.code}`).join('<br/>') || '无'
  const warnings = event.warnings.map((item) => item.code).join(', ') || '无'
  return `<b>${event.summary}</b><br/>类型: ${event.resonance_type}<br/>确认时间: ${event.time}<br/>证据:<br/>${evidence}<br/>风险: ${warnings}`
}

function buildOption(data: TimeframeAnalysis, ct: ReturnType<typeof useChartTheme>, resonance: ResonanceResult | null): EChartsOption {
  const dates = data.bars.map((b) => b.dt)
  const dateSet = new Set(dates)
  const candles = data.bars.map((b) => [b.open, b.close, b.low, b.high])

  const biMarkLine: any[] = data.bi
    .filter((b) => dateSet.has(b.sdt) && dateSet.has(b.edt))
    .map((b) => [
      { xAxis: b.sdt, yAxis: b.start_price },
      { xAxis: b.edt, yAxis: b.end_price },
    ])

  const zsMarkArea: any[] = data.zs
    .filter((z) => dateSet.has(z.sdt) && dateSet.has(z.edt))
    .map((z) => [
      { xAxis: z.sdt, yAxis: z.zd },
      { xAxis: z.edt, yAxis: z.zg },
    ])

  const bsMarkPoint: any[] = data.buy_sell
    .filter((p) => dateSet.has(p.dt) && TYPE_META[p.type])
    .map((p) => {
      const m = TYPE_META[p.type]
      const context = p.higher_timeframe_context.summary
      const color = context === '高周期冲突' ? '#F59E0B' : context === '逆高周期结构' ? '#94A3B8' : m.buy ? BULL : BEAR
      return {
        name: p.type,
        coord: [p.dt, p.price],
        symbol: 'arrow',
        symbolSize: 12,
        symbolRotate: m.buy ? 0 : 180,
        symbolOffset: m.buy ? [0, '60%'] : [0, '-60%'],
        itemStyle: { color, opacity: context === '逆高周期结构' ? 0.45 : 1 },
        label: {
          show: true,
          formatter: m.label,
          position: m.buy ? 'bottom' : 'top',
          distance: 6,
          color,
          fontSize: 10,
          fontFamily: 'JetBrains Mono, monospace',
        },
        tooltip: { formatter: () => signalTooltip(p) },
      }
    })
  const resonanceMarkPoint: any[] = []
  const event = resonance?.event
  if (event && data.timeframe === '日线') {
    const day = event.time.slice(0, 10)
    const bar = data.bars.find((item) => item.dt === day)
    if (bar) {
      resonanceMarkPoint.push({
        name: event.resonance_type,
        coord: [day, bar.close],
        symbol: 'star',
        symbolSize: 18,
        itemStyle: { color: event.direction === 'BEARISH' ? BEAR : event.direction === 'BULLISH' ? '#F59E0B' : '#94A3B8' },
        label: { show: true, formatter: event.resonance_type.replaceAll('_', '\n'), position: 'top', fontSize: 9, color: ct.text },
        tooltip: { formatter: () => resonanceTooltip(event) },
      })
    }
  }

  return {
    animation: false,
    grid: { left: 60, right: 20, top: 8, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: ct.tooltipBg,
      borderColor: ct.tooltipBorder,
      textStyle: { color: ct.tooltipText, fontSize: 11 },
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: true,
      axisLine: { lineStyle: { color: ct.border } },
      axisLabel: { color: ct.text, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    yAxis: {
      scale: true,
      boundaryGap: [0.03, 0.03],
      splitArea: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: ct.grid } },
      axisLabel: { color: ct.text, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0 },
      {
        type: 'slider',
        xAxisIndex: 0,
        height: 16,
        bottom: 4,
        borderColor: ct.border,
        textStyle: { color: ct.text, fontSize: 10 },
        fillerColor: ct.zoomFill,
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: candles,
        itemStyle: {
          color: BULL,
          color0: BEAR,
          borderColor: BULL,
          borderColor0: BEAR,
        },
        markLine: biMarkLine.length
          ? {
              symbol: 'none',
              silent: true,
              animation: false,
              data: biMarkLine,
              lineStyle: { color: BI_COLOR, width: 1.5, opacity: 0.85 },
            }
          : undefined,
        markArea: zsMarkArea.length
          ? {
              silent: true,
              data: zsMarkArea,
              itemStyle: { color: ZS_COLOR },
            }
          : undefined,
        markPoint: bsMarkPoint.length || resonanceMarkPoint.length
          ? { data: [...bsMarkPoint, ...resonanceMarkPoint], animation: false }
          : undefined,
      },
    ],
  }
}

function ChanlunFooter({
  symbol,
  name,
  view,
}: {
  symbol: string
  name: string | null
  view: 'daily' | 'intraday'
}) {
  const ct = useChartTheme()
  const chartRef = useRef<HTMLDivElement>(null)
  const chart = useRef<ECharts | null>(null)
  const resonanceRef = useRef<HTMLDivElement>(null)
  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [timeframe, setTimeframe] = useState('日线')
  const [loading, setLoading] = useState(false)
  const [syncJobId, setSyncJobId] = useState<string | null>(null)
  const [syncMessage, setSyncMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const requestVersion = useRef(0)

  // 缠论画图基于日线结构, 仅在日K视图显示
  useEffect(() => {
    if (view !== 'daily') {
      setData(null)
      setError(null)
    }
  }, [view])

  useEffect(() => {
    requestVersion.current += 1
    setData(null)
    setError(null)
    setTimeframe('日线')
    setSyncJobId(null)
    setSyncMessage(null)
  }, [symbol])

  useEffect(() => {
    if (!syncJobId) return
    let disposed = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const job = await api.pipelineJob(syncJobId)
        if (disposed) return
        if (job.status === 'succeeded') {
          setSyncJobId(null)
          setSyncMessage('分钟数据同步完成；请点击“开始分析”读取新数据。')
          return
        }
        if (job.status === 'failed') {
          setSyncJobId(null)
          setError(job.error || '分钟数据同步失败')
          return
        }
        setSyncMessage(`同步分钟数据：${job.progress}% · ${job.log.at(-1)?.msg ?? '准备中…'}`)
        timer = window.setTimeout(poll, 1200)
      } catch (e) {
        if (!disposed) {
          setSyncJobId(null)
          setError(e instanceof Error ? e.message : String(e))
        }
      }
    }
    void poll()
    return () => {
      disposed = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [syncJobId])

  const chartData = data?.timeframes[timeframe] ?? data?.timeframes['日线'] ?? null

  useEffect(() => {
    if (!chartRef.current || !chartData) return
    if (!chart.current) chart.current = echarts.init(chartRef.current)
    const currentChart = chart.current
    const eventName = data?.resonance?.event?.resonance_type
    const openResonanceDrilldown = (params: { componentType?: string; name?: string }) => {
      if (params.componentType !== 'markPoint' || params.name !== eventName) return
      setTimeframe('日线')
      resonanceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
    currentChart.setOption(buildOption(chartData, ct, timeframe === '日线' ? data?.resonance ?? null : null), true)
    currentChart.on('click', openResonanceDrilldown)
    return () => {
      currentChart.off('click', openResonanceDrilldown)
      currentChart.dispose()
      chart.current = null
    }
  }, [chartData, ct, data?.resonance, timeframe])

  useEffect(() => {
    const onResize = () => chart.current?.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  if (view !== 'daily') return null

  async function load() {
    const version = requestVersion.current + 1
    requestVersion.current = version
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/chan/analyze?symbol=${encodeURIComponent(symbol)}&days=250&minute_days=60`)
      const payload: AnalyzeResponse & { detail?: string } = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      if (requestVersion.current === version) setData(payload)
    } catch (e) {
      if (requestVersion.current === version) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (requestVersion.current === version) setLoading(false)
    }
  }

  async function syncNativeMinutes() {
    setError(null)
    setSyncMessage('正在创建分钟数据同步任务…')
    try {
      const result = await api.syncCzscMinutes(symbol, 250)
      setSyncJobId(result.job_id)
      if (result.daily_start && result.daily_end) {
        setSyncMessage(`按日线窗口 ${result.daily_start} ~ ${result.daily_end} 同步 15/30/60 分钟K…`)
      }
    } catch (e) {
      setSyncMessage(null)
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const meta = chartData
    ? `${chartData.bars.length} 根K线 · ${chartData.bi.length} 笔 · ${chartData.zs.length} 中枢 · ${chartData.buy_sell.length} 个结构信号`
    : null

  return (
    <div className="border-t border-border px-4 py-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">
            缠论结构 · {name ?? symbol}
          </span>
          {meta && <span className="text-xs text-secondary">{timeframe} · {meta}</span>}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-0.5 rounded bg-[#F59E0B]" /> 笔
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm bg-[#3B82F6]/20" /> 中枢
          </span>
          <span className="flex items-center gap-1"><span className="text-bull">B</span> 结构信号 / <span className="text-bear">S</span> 结构信号</span>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex h-8 items-center rounded-btn bg-elevated px-2.5 text-xs text-secondary transition-colors duration-150 ease-smooth hover:bg-elevated/80 hover:text-foreground disabled:opacity-50"
          >
            {loading ? '分析中…' : data ? '重新分析' : '开始分析'}
          </button>
          <button
            type="button"
            onClick={() => void syncNativeMinutes()}
            disabled={loading || syncJobId !== null}
            className="inline-flex h-8 items-center rounded-btn bg-accent/15 px-2.5 text-xs text-accent transition-colors duration-150 ease-smooth hover:bg-accent/25 disabled:opacity-50"
            title="按当前日线分析窗口，单独同步 TickFlow 原生 15m、30m、60m K线；不会开始 CZSC 分析"
          >
            {syncJobId ? '同步分钟数据中…' : '同步分钟数据'}
          </button>
        </div>
      </div>
      {data && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          {['15分钟', '30分钟', '60分钟', '日线'].map((item) => {
            const available = Boolean(data.timeframes[item])
            return (
              <button
                key={item}
                type="button"
                disabled={!available}
                onClick={() => setTimeframe(item)}
                className={`rounded-btn px-2 py-1 text-[11px] transition-colors ${timeframe === item ? 'bg-accent/15 text-accent' : 'bg-elevated text-muted hover:text-secondary'} disabled:cursor-not-allowed disabled:opacity-40`}
                title={available ? `${item} CZSC 结构` : '本地分钟K不足，当前不可用'}
              >
                {item}
              </button>
            )
          })}
          <span className="ml-1 text-[10px] text-muted">
            {data.minute_data_available ? `分钟来源：${data.base_frequency}` : '未发现本地分钟K，仅展示日线'}
          </span>
        </div>
      )}
      {data?.resonance && (
        <div ref={resonanceRef} className="mb-3 rounded-btn border border-border bg-elevated/40 p-2.5 text-xs">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-foreground">CZSC 多周期分析 · {data.resonance.summary}</span>
            <span className="text-muted">{data.resonance.current_only ? '仅当前状态；未回画历史共振' : ''}</span>
          </div>
          <div className="grid gap-1 sm:grid-cols-4">
            {['日线', '60分钟', '30分钟', '15分钟'].map((item) => {
              const state = data.resonance.timeframe_states[item]
              if (!state) return <span key={item} className="text-muted">{item}：数据不足</span>
              return (
                <button key={item} type="button" onClick={() => data.timeframes[item] && setTimeframe(item)} className="rounded bg-surface px-2 py-1 text-left hover:bg-elevated">
                  <div><span className="text-muted">{item} </span>{state.direction} · {state.native_state.values.v1} / {state.native_state.values.v2}</div>
                  <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-secondary">
                    {state.quality?.map((signal) => (
                      <span key={signal.id} title={signal.raw_signal} className="rounded bg-elevated px-1 py-0.5">
                        {signal.label}：{signal.values.v1}{signal.values.v2 === '任意' ? '' : `·${signal.values.v2}`}
                      </span>
                    ))}
                  </div>
                </button>
              )
            })}
          </div>
          {data.resonance.evidence.length > 0 && <div className="mt-2 text-secondary">证据：{data.resonance.evidence.map((item) => item.code).join(' · ')}</div>}
          {data.resonance.warnings.length > 0 && <div className="mt-1 text-amber-500">风险：{data.resonance.warnings.map((item) => item.code).join(' · ')}</div>}
        </div>
      )}
      {error && <div className="mb-2 text-xs text-red-500">{error}</div>}
      {syncMessage && <div className="mb-2 text-xs text-secondary">{syncMessage}</div>}
      {!data && !loading && !error && (
        <div className="text-xs text-muted">
          「开始分析」只读取本地数据；先点「同步分钟数据」可按当前日线窗口拉取原生 15 / 30 / 60 分钟K。
        </div>
      )}
      <div ref={chartRef} className="h-[560px] w-full" />
    </div>
  )
}

const chanlunSlots: FrontendSlotRegistration<'stock-preview.footer'>[] = [
  {
    name: 'stock-preview.footer',
    id: 'chanlun-stock-footer',
    component: ChanlunFooter,
  },
]

const extension: FrontendExtension = {
  id: 'local.chanlun',
  apiVersion: 1,
  slots: chanlunSlots,
}

export default extension

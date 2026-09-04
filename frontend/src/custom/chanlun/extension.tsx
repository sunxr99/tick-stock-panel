import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import type { ECharts, EChartsOption } from 'echarts'
import { useChartTheme } from '@/lib/theme'
import type { FrontendExtension, FrontendSlotRegistration } from '@/extensions/types'

type AnalyzeResponse = {
  symbol: string
  asset_type: string
  bars_count: number
  bi_count: number
  zs_count: number
  buy_sell_count: number
  bars: { dt: string; open: number; high: number; low: number; close: number; vol: number }[]
  bi: {
    sdt: string
    edt: string
    direction: string
    start_price: number
    end_price: number
    high: number
    low: number
    power: number
  }[]
  zs: { sdt: string; edt: string; zg: number; zd: number; gg: number; dd: number }[]
  buy_sell: { dt: string; type: string; price: number }[]
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

function buildOption(data: AnalyzeResponse, ct: ReturnType<typeof useChartTheme>): EChartsOption {
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
      return {
        name: p.type,
        coord: [p.dt, p.price],
        symbol: 'arrow',
        symbolSize: 12,
        symbolRotate: m.buy ? 0 : 180,
        symbolOffset: m.buy ? [0, '60%'] : [0, '-60%'],
        itemStyle: { color: m.buy ? BULL : BEAR },
        label: {
          show: true,
          formatter: m.label,
          position: m.buy ? 'bottom' : 'top',
          distance: 6,
          color: m.buy ? BULL : BEAR,
          fontSize: 10,
          fontFamily: 'JetBrains Mono, monospace',
        },
      }
    })

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
        markPoint: bsMarkPoint.length
          ? { data: bsMarkPoint, animation: false }
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
  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 缠论画图基于日线结构, 仅在日K视图显示
  useEffect(() => {
    if (view !== 'daily') {
      setData(null)
      setError(null)
    }
  }, [view])

  useEffect(() => {
    if (!chartRef.current || !data) return
    if (!chart.current) chart.current = echarts.init(chartRef.current)
    chart.current.setOption(buildOption(data, ct), true)
    return () => {
      chart.current?.dispose()
      chart.current = null
    }
  }, [data, ct])

  useEffect(() => {
    const onResize = () => chart.current?.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  if (view !== 'daily') return null

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/chan/analyze?symbol=${encodeURIComponent(symbol)}&days=250`)
      const payload: AnalyzeResponse & { detail?: string } = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setData(payload)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const meta = data
    ? `${data.bars_count} 根K线 · ${data.bi_count} 笔 · ${data.zs_count} 中枢 · ${data.buy_sell_count} 个买卖点`
    : null

  return (
    <div className="border-t border-border px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">
            缠论结构 · {name ?? symbol}
          </span>
          {meta && <span className="text-xs text-secondary">{meta}</span>}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-0.5 rounded bg-[#F59E0B]" /> 笔
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm bg-[#3B82F6]/20" /> 中枢
          </span>
          <span className="flex items-center gap-1">
            <span className="text-bull">B</span> 买 / <span className="text-bear">S</span> 卖
          </span>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex h-8 items-center rounded-btn bg-elevated px-2.5 text-xs text-secondary transition-colors duration-150 ease-smooth hover:bg-elevated/80 hover:text-foreground disabled:opacity-50"
          >
            {loading ? '分析中…' : data ? '重新分析' : '开始分析'}
          </button>
        </div>
      </div>
      {error && <div className="mb-2 text-xs text-red-500">{error}</div>}
      {!data && !loading && !error && (
        <div className="text-xs text-muted">
          点击「开始分析」计算该股的笔 / 中枢 / 买卖点结构
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

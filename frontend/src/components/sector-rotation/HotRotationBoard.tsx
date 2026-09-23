import { useState } from 'react'
import { EastmoneyHotRotationBoard } from '@/components/sector-rotation/EastmoneyHotRotationBoard'
import { SectorRotationBoard } from '@/components/sector-rotation/SectorRotationBoard'
import { TdxHotRotationBoard } from '@/components/sector-rotation/TdxHotRotationBoard'
import { cn } from '@/lib/cn'

type Source = 'eastmoney' | 'tdx' | 'ths'

export function HotRotationBoard() {
  const [source, setSource] = useState<Source>('eastmoney')
  return <div className="space-y-3">
    <div className="flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2">
      <span className="text-xs text-muted">热点数据源</span>
      <div className="flex rounded-lg border border-border bg-elevated/40 p-0.5">
        <button type="button" onClick={() => setSource('eastmoney')} className={cn('rounded-md px-2.5 py-1 text-xs transition-colors', source === 'eastmoney' ? 'bg-accent text-white' : 'text-muted hover:text-foreground')}>东方财富</button>
        <button type="button" onClick={() => setSource('tdx')} className={cn('rounded-md px-2.5 py-1 text-xs transition-colors', source === 'tdx' ? 'bg-accent text-white' : 'text-muted hover:text-foreground')}>通达信</button>
        <button type="button" onClick={() => setSource('ths')} className={cn('rounded-md px-2.5 py-1 text-xs transition-colors', source === 'ths' ? 'bg-accent text-white' : 'text-muted hover:text-foreground')}>同花顺</button>
      </div>
      <span className="text-[11px] text-muted">{source === 'eastmoney' ? '主题 / 短线情绪 / 风格条件可切换' : source === 'tdx' ? '概念 / 行业 / 风格可切换；全部含地区板块' : '同花顺概念成员快照计算的轮动强度'}</span>
    </div>
    {source === 'eastmoney' ? <EastmoneyHotRotationBoard /> : source === 'tdx' ? <TdxHotRotationBoard /> : <SectorRotationBoard kind="concept" />}
  </div>
}

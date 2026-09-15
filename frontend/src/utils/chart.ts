/* 簡易折線圖（canvas） */
import { fmtTime } from './format'

export interface ChartSeries {
  label: string
  color: string
  values: (number | null | undefined)[]
  width?: number
}

export interface ChartOptions {
  title?: string
  empty?: string
  lines?: { value: number; color?: string }[]
  minSpan?: number
  decimals?: number
}

export function drawChart(canvas: HTMLCanvasElement, ts: number[], series: ChartSeries[], opts: ChartOptions = {}): void {
  const dpr = window.devicePixelRatio || 1
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  if (!w || !h) return
  canvas.width = w * dpr
  canvas.height = h * dpr
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)
  const padL = 34
  const padR = 8
  const padT = 20
  const padB = 16
  const pw = w - padL - padR
  const ph = h - padT - padB
  ctx.font = '600 11px sans-serif'
  ctx.fillStyle = '#344054'
  ctx.textBaseline = 'top'
  ctx.textAlign = 'left'
  ctx.fillText(opts.title ?? '', 4, 3)
  const vals: number[] = []
  series.forEach((s) => s.values.forEach((v) => { if (v != null) vals.push(v) }))
  if (!vals.length || ts.length < 2) {
    ctx.fillStyle = '#98a2b3'
    ctx.font = '12px sans-serif'
    ctx.fillText(opts.empty ?? '無資料', padL, h / 2 - 6)
    return
  }
  ;(opts.lines ?? []).forEach((l) => vals.push(l.value))
  let lo = Math.min(...vals)
  let hi = Math.max(...vals)
  const span = opts.minSpan ?? 10
  if (hi - lo < span) {
    const c = (hi + lo) / 2
    lo = c - span / 2
    hi = c + span / 2
  }
  const padV = (hi - lo) * 0.08
  lo -= padV
  hi += padV
  const t0 = ts[0] ?? 0
  const t1 = ts[ts.length - 1] ?? 0
  const x = (t: number) => padL + ((t - t0) / (t1 - t0 || 1)) * pw
  const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * ph
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'right'
  ctx.textBaseline = 'middle'
  for (let k = 0; k <= 3; k++) {
    const v = lo + ((hi - lo) * k) / 3
    ctx.strokeStyle = '#eef1f5'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(padL, y(v))
    ctx.lineTo(w - padR, y(v))
    ctx.stroke()
    ctx.fillStyle = '#98a2b3'
    ctx.fillText(v.toFixed(opts.decimals ?? 0), padL - 4, y(v))
  }
  ;(opts.lines ?? []).forEach((l) => {
    ctx.strokeStyle = l.color ?? '#f04438'
    ctx.setLineDash([4, 3])
    ctx.beginPath()
    ctx.moveTo(padL, y(l.value))
    ctx.lineTo(w - padR, y(l.value))
    ctx.stroke()
    ctx.setLineDash([])
  })
  series.forEach((s) => {
    ctx.strokeStyle = s.color
    ctx.lineWidth = s.width ?? 1.8
    ctx.beginPath()
    let started = false
    s.values.forEach((v, k) => {
      const t = ts[k]
      if (v == null || t == null) {
        started = false
        return
      }
      if (!started) {
        ctx.moveTo(x(t), y(v))
        started = true
      } else {
        ctx.lineTo(x(t), y(v))
      }
    })
    ctx.stroke()
  })
  ctx.textAlign = 'right'
  ctx.textBaseline = 'top'
  ctx.font = '600 11px sans-serif'
  let lx = w - padR
  ;[...series].reverse().forEach((s) => {
    const last = [...s.values].reverse().find((v) => v != null)
    const txt = `${s.label} ${last == null ? '-' : opts.decimals ? last.toFixed(opts.decimals) : Math.round(last)}`
    ctx.fillStyle = s.color
    ctx.fillText(txt, lx, 3)
    lx -= ctx.measureText(txt).width + 10
  })
  ctx.fillStyle = '#98a2b3'
  ctx.font = '10px sans-serif'
  ctx.textBaseline = 'bottom'
  ctx.textAlign = 'left'
  ctx.fillText(fmtTime(t0), padL, h)
  ctx.textAlign = 'right'
  ctx.fillText(fmtTime(t1), w - padR, h)
}

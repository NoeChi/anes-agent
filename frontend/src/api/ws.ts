/* WebSocket 即時連線：自動重連，依事件類型分派給訂閱者 */
import { getCurrentInstance, onUnmounted, reactive } from 'vue'
import type { WsEventMap } from './types'

type Listener = (data: unknown) => void

const listeners = new Map<string, Set<Listener>>()

export const wsState = reactive({ connected: false, attempted: false })

export function onWs<K extends keyof WsEventMap>(type: K, fn: (data: WsEventMap[K]) => void): () => void {
  let set = listeners.get(type)
  if (!set) {
    set = new Set()
    listeners.set(type, set)
  }
  const listener = fn as Listener
  set.add(listener)
  return () => {
    set.delete(listener)
  }
}

/** 在元件內訂閱事件，元件卸載時自動取消 */
export function useWs<K extends keyof WsEventMap>(type: K, fn: (data: WsEventMap[K]) => void): void {
  const off = onWs(type, fn)
  if (getCurrentInstance()) onUnmounted(off)
}

function dispatch(type: string, data: unknown): void {
  listeners.get(type)?.forEach((fn) => {
    try {
      fn(data)
    } catch (e) {
      console.error('[ws]', type, e)
    }
  })
}

let started = false
let retry = 1000

function open(): void {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
  ws.onopen = () => {
    retry = 1000
    wsState.connected = true
    wsState.attempted = true
  }
  ws.onmessage = (e: MessageEvent) => {
    let msg: { type: string; data: unknown }
    try {
      msg = JSON.parse(String(e.data))
    } catch {
      return
    }
    dispatch(msg.type, msg.data)
  }
  ws.onclose = () => {
    wsState.connected = false
    wsState.attempted = true
    setTimeout(open, retry)
    retry = Math.min(retry * 2, 10000)
  }
}

export function connectWs(): void {
  if (started) return
  started = true
  open()
}

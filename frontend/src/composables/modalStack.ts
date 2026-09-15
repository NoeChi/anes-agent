/* 追蹤開啟中的對話框，讓 Esc 只關閉最上層那一個 */
const stack: number[] = []
let seq = 0

export function pushModal(): number {
  const id = ++seq
  stack.push(id)
  return id
}

export function popModal(id: number): void {
  const i = stack.indexOf(id)
  if (i >= 0) stack.splice(i, 1)
}

export function isTopModal(id: number): boolean {
  return stack[stack.length - 1] === id
}

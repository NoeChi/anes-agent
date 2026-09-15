/* 安全的簡易 Markdown：先跳脫所有 HTML，再轉換常用語法（標題、粗體、行內程式碼、清單、表格、引言、程式區塊） */

export function escapeHtml(s: unknown): string {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c)
}

const inline = (s: string): string => s.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
const isList = (l: string): boolean => /^\s*([-*]|\d+[.)])\s+/.test(l)
const isTable = (l: string): boolean => /^\s*\|.*\|\s*$/.test(l)

export function md(src: string | null | undefined): string {
  if (!src) return ''
  const lines = escapeHtml(src).split('\n')
  let html = ''
  let i = 0
  while (i < lines.length) {
    const line = lines[i] ?? ''
    if (/^```/.test(line)) {
      const buf: string[] = []
      i++
      while (i < lines.length && !/^```/.test(lines[i] ?? '')) buf.push(lines[i++] ?? '')
      i++
      html += `<pre><code>${buf.join('\n')}</code></pre>`
      continue
    }
    const h = line.match(/^(#{1,6})\s+(.*)/)
    if (h) {
      const lv = Math.min(6, (h[1] ?? '#').length + 1)
      html += `<h${lv}>${inline(h[2] ?? '')}</h${lv}>`
      i++
      continue
    }
    if (isTable(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] ?? '')) {
      const cells = (l: string) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()))
      const head = cells(line)
      i += 2
      let rows = ''
      while (i < lines.length && isTable(lines[i] ?? '')) {
        rows += '<tr>' + cells(lines[i] ?? '').map((c) => `<td>${c}</td>`).join('') + '</tr>'
        i++
      }
      html += `<div class="table-wrap"><table><thead><tr>${head.map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`
      continue
    }
    if (isList(line)) {
      const ordered = /^\s*\d+[.)]/.test(line)
      let items = ''
      while (i < lines.length && isList(lines[i] ?? '')) {
        const cur = lines[i] ?? ''
        const indent = (cur.match(/^\s*/)?.[0] ?? '').length
        const text = cur.replace(/^\s*([-*]|\d+[.)])\s+/, '')
        items += `<li${indent >= 2 ? ' class="sub"' : ''}>${inline(text)}</li>`
        i++
      }
      html += ordered ? `<ol>${items}</ol>` : `<ul>${items}</ul>`
      continue
    }
    if (/^&gt;\s?/.test(line)) {
      const buf: string[] = []
      while (i < lines.length && /^&gt;\s?/.test(lines[i] ?? '')) buf.push((lines[i++] ?? '').replace(/^&gt;\s?/, ''))
      html += `<blockquote>${inline(buf.join('<br>'))}</blockquote>`
      continue
    }
    if (/^\s*(---|\*\*\*)\s*$/.test(line)) {
      html += '<hr>'
      i++
      continue
    }
    if (!line.trim()) {
      i++
      continue
    }
    const buf = [line]
    i++
    while (i < lines.length) {
      const next = lines[i] ?? ''
      if (!next.trim() || /^(#{1,6}\s|```|&gt;)/.test(next) || isList(next) || isTable(next)) break
      buf.push(next)
      i++
    }
    html += `<p>${inline(buf.join('<br>'))}</p>`
  }
  return html
}

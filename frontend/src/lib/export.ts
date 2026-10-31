/** 只导出当前正文；不持久化、上传附件或请求外部资源。 */
import { ACCOUNT_CHANGED_EVENT, SESSION_EXPIRED_EVENT } from './api'

export function exportFilename(name: string, extension: 'md' | 'docx'): string {
  const safe = name.replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, '-').replace(/[. ]+$/g, '').trim().slice(0, 80)
  return `${safe || '职得offer'}-定向简历.${extension}`
}

function requireMarkdown(markdown: string) {
  if (!markdown.trim()) throw new Error('暂无简历正文，请先生成简历。')
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  try { anchor.click() } finally {
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}

export function downloadMarkdown(markdown: string, name = '职得offer') {
  requireMarkdown(markdown)
  saveBlob(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }), exportFilename(name, 'md'))
}

export async function downloadWord(markdown: string, name = '职得offer', signal?: AbortSignal) {
  requireMarkdown(markdown)
  const controller = new AbortController()
  const cancel = () => controller.abort()
  const timeout = window.setTimeout(cancel, 30000)
  signal?.addEventListener('abort', cancel, { once: true })
  window.addEventListener(ACCOUNT_CHANGED_EVENT, cancel)
  window.addEventListener(SESSION_EXPIRED_EVENT, cancel)
  if (signal?.aborted) cancel()
  try {
    const response = await fetch('/api/export/docx', {
      method: 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({ markdown, name }),
    })
    if (!response.ok) {
      if (response.status === 401 && !controller.signal.aborted) window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : `Word 导出失败（${response.status}），请确认导出服务已接入后重试。`)
    }
    if (!response.headers.get('Content-Type')?.includes('application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
      throw new Error('导出服务未返回 Word 文件，请联系负责人检查路由接入。')
    }
    const blob = await response.blob()
    if (controller.signal.aborted) throw new Error('导出已取消，请重新操作。')
    saveBlob(blob, exportFilename(name, 'docx'))
  } finally {
    window.clearTimeout(timeout)
    signal?.removeEventListener('abort', cancel)
    window.removeEventListener(ACCOUNT_CHANGED_EVENT, cancel)
    window.removeEventListener(SESSION_EXPIRED_EVENT, cancel)
  }
}

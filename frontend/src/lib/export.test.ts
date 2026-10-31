import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { downloadMarkdown, downloadWord, exportFilename } from './export'

let anchor: { href: string; download: string; click: ReturnType<typeof vi.fn>; remove: ReturnType<typeof vi.fn> }
let create: ReturnType<typeof vi.fn>
let revoke: ReturnType<typeof vi.fn>
beforeEach(() => {
  anchor = { href: '', download: '', click: vi.fn(), remove: vi.fn() }
  vi.useFakeTimers()
  const surface = new EventTarget()
  vi.stubGlobal('window', Object.assign(surface, { setTimeout, clearTimeout }))
  vi.stubGlobal('document', { createElement: () => anchor, body: { appendChild: vi.fn() } })
  create = vi.fn(() => 'blob:demo'); revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('resume exports', () => {
  it('preserves Markdown verbatim and releases the download URL', async () => {
    downloadMarkdown('# 虚构\n\n**正文**', '../林:同学')
    expect(anchor.download).not.toMatch(/[\\/:]/)
    expect(await (create.mock.calls[0][0] as Blob).text()).toBe('# 虚构\n\n**正文**')
    expect(anchor.click).toHaveBeenCalledOnce()
    expect(anchor.remove).toHaveBeenCalledOnce()
    vi.runAllTimers()
    expect(revoke).toHaveBeenCalledWith('blob:demo')
    expect(exportFilename('   ', 'docx')).toBe('职得offer-定向简历.docx')
  })
  it('rejects empty content without sending or downloading', async () => {
    const request = vi.fn(); vi.stubGlobal('fetch', request)
    expect(() => downloadMarkdown('  ')).toThrow('暂无简历')
    await expect(downloadWord('\n')).rejects.toThrow('暂无简历')
    expect(request).not.toHaveBeenCalled()
    expect(anchor.click).not.toHaveBeenCalled()
  })
  it('shows service errors and never downloads HTML as Word', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>fallback</html>', { headers: { 'Content-Type': 'text/html' } })))
    await expect(downloadWord('# 简历')).rejects.toThrow('未返回 Word 文件')
    expect(anchor.click).not.toHaveBeenCalled()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: '服务繁忙' }), { status: 503 })))
    await expect(downloadWord('# 简历')).rejects.toThrow('服务繁忙')
  })
  it('sends the existing CSRF header and downloads only a real DOCX response', async () => {
    const request = vi.fn().mockResolvedValue(new Response('docx bytes', { headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' } }))
    vi.stubGlobal('fetch', request)
    await downloadWord('# 简历', '演示')
    expect(request.mock.calls[0][1].headers['X-Requested-With']).toBe('XMLHttpRequest')
    expect(JSON.parse(request.mock.calls[0][1].body).markdown).toBe('# 简历')
    expect(anchor.download).toBe('演示-定向简历.docx')
    expect(anchor.click).toHaveBeenCalledOnce()
  })
  it('discards a response arriving after an account change', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      window.dispatchEvent(new Event('zhide:account-changed'))
      return new Response('docx', { headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' } })
    }))
    await expect(downloadWord('# 私有简历')).rejects.toThrow('已取消')
    expect(anchor.click).not.toHaveBeenCalled()
  })
})

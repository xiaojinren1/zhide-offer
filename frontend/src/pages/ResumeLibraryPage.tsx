import { useEffect, useRef, useState } from 'react'
import { downloadMarkdown, downloadPdf, downloadWord, printResume } from '../lib/export'
import ResumePreview, { defaultResumeAppearance, type ResumeAppearance } from './workbench/ResumePreview'
import './workbench/workbench.css'

interface Props {
  markdown: string
  name: string
  appearance?: ResumeAppearance | null
  onOpenWorkbench: () => void
}

export default function ResumeLibraryPage({ markdown, name, appearance, onOpenWorkbench }: Props) {
  const canvas = useRef<HTMLDivElement>(null)
  const activeExport = useRef<AbortController | null>(null)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const style = appearance ?? defaultResumeAppearance
  useEffect(() => () => activeExport.current?.abort(), [])

  async function exportWord() {
    if (activeExport.current) return
    const controller = new AbortController()
    activeExport.current = controller
    setExporting(true)
    setError('')
    try {
      await downloadWord(markdown, name, controller.signal, style)
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Word 下载失败，请重试。')
    } finally {
      activeExport.current = null
      if (!controller.signal.aborted) setExporting(false)
    }
  }

  async function downloadPdfFile() {
    if (activeExport.current) return
    const controller = new AbortController()
    activeExport.current = controller
    setExporting(true)
    setError('')
    try {
      // 服务端按当前模板渲染 PDF（含纸张底色与字号），浏览器打印是另一条路，两者都保留
      await downloadPdf(markdown, name, controller.signal, style)
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'PDF 下载失败，请重试。')
    } finally {
      activeExport.current = null
      if (!controller.signal.aborted) setExporting(false)
    }
  }

  return <div className="role-b-workbench">
    <section className="panel" aria-labelledby="current-resume-title">
      <div className="panel-heading">
        <h2 id="current-resume-title">当前简历</h2>
        <button type="button" className="secondary-button" onClick={onOpenWorkbench}>
          {markdown.trim() ? '前往工作台编辑' : '前往工作台制作简历'}
        </button>
      </div>
      {markdown.trim() ? <>
        <div className="wb-actions" aria-label="下载当前简历">
          <button type="button" className="primary-button" onClick={() => {
            if (canvas.current) printResume(canvas.current, name)
          }}>按预览保存 PDF</button>
          <button type="button" className="secondary-button" disabled={exporting}
            onClick={() => void exportWord()}>{exporting ? '正在导出 Word…' : '下载 Word'}</button>
          <button type="button" className="secondary-button" disabled={exporting}
            onClick={() => void downloadPdfFile()}>{exporting ? '正在导出 PDF…' : '下载 PDF 文件'}</button>
          <button type="button" className="secondary-button"
            onClick={() => downloadMarkdown(markdown, name)}>下载 Markdown</button>
        </div>
        {error && <p className="warning-note" role="alert">{error}</p>}
        <div className="resume-preview-canvas" ref={canvas} style={{ backgroundColor: style.background }}>
          <ResumePreview markdown={markdown} appearance={style} />
        </div>
      </> : <p className="panel-description">暂无简历。工作台生成的简历会显示在这里。</p>}
    </section>
  </div>
}

import type { CSSProperties, ReactNode } from 'react'

export const defaultResumeAppearance = {
  template: 'classic' as 'classic' | 'sidebar' | 'compact',
  background: '#edf2f8',
  paper: '#ffffff',
  accent: '#254264',
  fontSize: 14,
  spacing: 1.6,
}

export type ResumeAppearance = typeof defaultResumeAppearance & {
  headerAlign?: 'left' | 'center'
  sidebarSide?: 'left' | 'right'
  headerStyle?: 'standard' | 'portrait'
  portrait?: string | null
  nameColor?: string | null
  headingFont?: 'sans' | 'serif'
}

// 使用 React 文本节点，不注入模型 HTML，不生成来自正文的可执行链接。
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) return <em key={index}>{part.slice(1, -1)}</em>
    return part
  })
}

export default function ResumePreview({ markdown, appearance = defaultResumeAppearance }: {
  markdown: string
  appearance?: ResumeAppearance
}) {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  const portraitHeader = appearance.headerStyle === 'portrait'
  let firstSection = -1
  let paragraph: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (paragraph.length) {
      const text = paragraph.join('\n')
      const fields = text.split(/[|｜\n]/).map(field => field.trim()).filter(Boolean)
      const contactGrid = portraitHeader && firstSection < 0 && fields.length > 1 &&
        fields.every(field => /^[^：:]{1,12}[：:]/.test(field))
      blocks.push(contactGrid
        ? <div key={blocks.length} className="resume-contact-grid">{fields.map((field, index) => <span key={index}>{inline(field)}</span>)}</div>
        : <p key={blocks.length}>{inline(text)}</p>)
      paragraph = []
    }
    if (list) {
      const Tag = list.ordered ? 'ol' : 'ul'
      blocks.push(<Tag key={blocks.length}>{list.items.map((item, index) => <li key={index}>{inline(item)}</li>)}</Tag>)
      list = null
    }
  }
  for (const line of lines) {
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+)$/)
    const bullet = line.match(/^\s*(?:[-+*]|\d+[.)])\s+(.+)$/)
    if (heading) {
      flush()
      const Tag = heading[1].length === 1 ? 'h2' : heading[1].length === 2 ? 'h3' : 'h4'
      if (Tag === 'h3' && firstSection < 0) firstSection = blocks.length
      blocks.push(<Tag key={blocks.length}>{inline(heading[2])}</Tag>)
    } else if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flush(); blocks.push(<hr key={blocks.length} />)
    } else if (bullet) {
      const ordered = /^\s*\d/.test(line)
      if (paragraph.length || (list && list.ordered !== ordered)) flush()
      list ??= { ordered, items: [] }
      list.items.push(bullet[1])
    } else if (!line.trim()) {
      flush()
    } else {
      if (list) flush()
      paragraph.push(line)
    }
  }
  flush()
  const style = {
    '--resume-paper': appearance.paper,
    '--resume-accent': appearance.accent,
    '--resume-name-color': appearance.nameColor ?? appearance.accent,
    '--resume-size': `${appearance.fontSize}px`,
    '--resume-spacing': appearance.spacing,
  } as CSSProperties
  const headerEnd = firstSection < 0 ? blocks.length : firstSection
  const safePortrait = /^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(appearance.portrait ?? '')
  return <article className="resume-paper" data-template={appearance.template} data-header-align={appearance.headerAlign}
    data-header-style={appearance.headerStyle}
    data-heading-font={appearance.headingFont ?? 'sans'}
    data-sidebar-side={appearance.sidebarSide} style={style} aria-label="简历正文预览">
    {portraitHeader ? <>
      <header className="resume-portrait-header">
        <div>{blocks.slice(0, headerEnd)}</div>
        {safePortrait ? <img className="resume-portrait" src={appearance.portrait!} alt="简历证件照" />
          : <span className="resume-portrait resume-portrait-placeholder">证件照</span>}
      </header>
      {blocks.slice(headerEnd)}
    </> : appearance.template === 'sidebar' && firstSection > 0 ? <div className="resume-sidebar-layout">
      <div className="resume-sidebar-intro">{blocks.slice(0, firstSection)}</div>
      <div>{blocks.slice(firstSection)}</div>
    </div> : blocks}
  </article>
}

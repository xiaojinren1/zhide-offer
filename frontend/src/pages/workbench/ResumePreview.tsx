import type { ReactNode } from 'react'

// 使用 React 文本节点，不注入模型 HTML，不生成来自正文的可执行链接。
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) return <em key={index}>{part.slice(1, -1)}</em>
    return part
  })
}

export default function ResumePreview({ markdown }: { markdown: string }) {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let paragraph: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (paragraph.length) {
      blocks.push(<p key={blocks.length}>{inline(paragraph.join('\n'))}</p>)
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
  return <article className="resume-paper" aria-label="简历正文预览">{blocks}</article>
}

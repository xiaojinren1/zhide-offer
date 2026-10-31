import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ResumePreview from './ResumePreview'

describe('简历安全预览（真实 React 服务端渲染）', () => {
  it('渲染标题、段落、列表和行内格式', () => {
    const html = renderToStaticMarkup(<ResumePreview markdown={'# 虚构同学\r\n\r\n## 项目\r\n- **需求整理**\r\n- 使用 `SQL`\r\n\r\n1. *沟通*\r\n2. 文档\r\n\r\n---\r\n普通段落'} />)
    expect(html).toContain('<h2>虚构同学</h2>')
    expect(html).toContain('<h3>项目</h3>')
    expect(html).toContain('<ul><li><strong>需求整理</strong></li><li>使用 <code>SQL</code></li></ul>')
    expect(html).toContain('<ol><li><em>沟通</em></li><li>文档</li></ol>')
    expect(html).toContain('<hr/>')
    expect(html).toContain('<p>普通段落</p>')
  })
  it('HTML 和危险链接只作文本，不生成可执行标签或链接', () => {
    const html = renderToStaticMarkup(<ResumePreview markdown={'<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n[点击](javascript:alert(1))'} />)
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('<a ')
    expect(html).toContain('&lt;script&gt;')
  })
  it('空正文不会产生假内容', () => {
    expect(renderToStaticMarkup(<ResumePreview markdown={' \n\n'} />)).not.toContain('<p>')
  })
})

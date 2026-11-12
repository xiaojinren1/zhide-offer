import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ResumePreview, { defaultResumeAppearance } from './ResumePreview'
import { readResumeTemplate, readTemplatePreset } from './ResumeAppearanceControls'

describe('简历模板导入', () => {
  it('证件照页眉保留原有联系信息，正文在页眉之外', () => {
    const html = renderToStaticMarkup(<ResumePreview
      markdown={'# 示例姓名\n\n电话：示例号码 | 邮箱：示例地址\n\n## 工作经历\n示例正文'}
      appearance={{ ...defaultResumeAppearance, headerStyle: 'portrait' }}
    />)
    expect(html).toContain('class="resume-contact-grid"')
    expect(html).toContain('证件照')
    expect(html.indexOf('</header>')).toBeLessThan(html.indexOf('<h3>工作经历</h3>'))
  })
  it('还原外观参数并忽略模板中的正文和额外字段', () => {
    const appearance = { ...defaultResumeAppearance, template: 'sidebar', paper: '#f4f4ee' }
    expect(readResumeTemplate(JSON.stringify({
      version: 1, appearance: { ...appearance, markdown: '不应被导入' },
    }))).toEqual(appearance)
  })

  it('模板库下发的参数可直接收窄成外观，坏参数返回空', () => {
    const appearance = { ...defaultResumeAppearance, template: 'sidebar', accent: '#3c5a78' }
    expect(readTemplatePreset(appearance)).toEqual({ ...appearance, headerAlign: undefined,
      sidebarSide: undefined, headerStyle: undefined, nameColor: undefined, headingFont: undefined })
    expect(readTemplatePreset({ ...appearance, fontSize: 22 })).toBeNull()
    expect(readTemplatePreset({ ...appearance, accent: 'blue' })).toBeNull()
  })

  it('拒绝不兼容的版本、颜色和行距', () => {
    expect(readResumeTemplate(JSON.stringify({ version: 2, appearance: defaultResumeAppearance }))).toBeNull()
    expect(readResumeTemplate(JSON.stringify({ version: 1, appearance: { ...defaultResumeAppearance, paper: 'url(example)' } }))).toBeNull()
    expect(readResumeTemplate(JSON.stringify({ version: 1, appearance: { ...defaultResumeAppearance, spacing: 0 } }))).toBeNull()
  })
})

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

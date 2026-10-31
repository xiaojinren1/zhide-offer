# 角色 D 行为与接入契约

## 行为
- 个人记忆页只使用现有 profiles API；列表显示名称、保存时间和经历数，支持刷新、查看详情、载入和二次确认删除。
- 载入要求二次确认，回调返回事实确认已撤销的独立副本；A 必须原子替换 profile/source_text/source_name、清空 markdown 后回到工作台。载入不改 JD，不直接生成。
- 删除只删除经历库快照，不删除已载入工作台或面试记录；删除失败保留列表并允许重试。
- 不写浏览器持久存储。卸载、用户切换和账户失效后忽略旧请求结果；接入方必须传 userId 并按账户 key 重挂载。
- 导出仅针对传入的当前简历正文；Markdown 原样保存，Word 支持标题、段落、有序/无序列表、分隔线和常用行内标记。复杂 Markdown 表格/图片保持文本，不执行 HTML、不抓取远程地址。
- Word 服务端要求现有登录与 CSRF 请求头，流式返回 DOCX，不留存文件、不调用模型。正文为空、超限或包含不合法控制字符会拒绝。PDF 未实现，不显示可用按钮。

## A 的最小接入（本角色不改 App.tsx / api.ts / main.py）
1. `backend/main.py` 路由模块元组加入 `api.export`（模块自身也配置登录/CSRF 依赖）。
2. App 导入 `MemoryPage` 并用以下组件替换 memory-placeholder：

```tsx
<MemoryPage key={user.id} userId={user.id} markdown={markdown}
  resumeName={profile?.name || '职得offer'} disabled={busy || loggingOut || !persistence.loaded}
  onLoad={(loaded, meta) => update(previous => ({ ...previous,
    profile: loaded, source_text: loaded.raw_text || '', source_name: meta.name || '已保存经历库',
    markdown: '', page: 'workbench',
  }))} />
```

3. B 如需工作台按钮，可调用 `downloadMarkdown(markdown, name)` 和 `await downloadWord(markdown, name)`（来自 `frontend/src/lib/export.ts`）；务必捕获错误并展示，禁止空稿导出。
4. PDF 尚未实现。Word 路由未接入前会明确报错，不回退生成伪造文件。

## 验收边界
模块测试、构建和后端临时数据库测试结果见本目录验收记录。主页面导航、真实浏览器布局、真实 Word 排版和外部模型需在 A 接入后另验；不能将模块完成表述为已上线。

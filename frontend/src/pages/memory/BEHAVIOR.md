# 角色 D 行为与接入契约

## 行为
- 个人记忆页使用账户隔离的 profiles API；列表显示名称、保存时间和经历数，支持刷新、查看详情、载入和二次确认删除。
- 载入要求二次确认，回调返回事实确认已撤销的独立副本；A 必须原子替换 profile/source_text/source_name、清空 markdown 后回到工作台。载入不改 JD，不直接生成。
- 删除只删除经历库快照，不删除已载入工作台或面试记录；删除失败保留列表并允许重试。
- 不写浏览器持久存储。卸载、用户切换和账户失效后忽略旧请求结果；接入方必须传 userId 并按账户 key 重挂载。
- 导出仅针对传入的当前简历正文；Markdown 原样保存，Word 支持标题、段落、有序/无序列表、分隔线和常用行内标记。复杂 Markdown 表格/图片保持文本，不执行 HTML、不抓取远程地址。
- Word 服务端要求现有登录与 CSRF 请求头，流式返回 DOCX，不留存文件、不调用模型。正文为空、超限或包含不合法控制字符会拒绝。PDF 未实现，不显示可用按钮。

## 当前主页面接入
1. `backend/main.py` 路由模块元组已加入 `api.export`（模块自身也配置登录/CSRF 依赖）。
2. App 已接入 `MemoryPage`；更新时继续保持以下原子载入契约，并传入 currentProfile 和 hasUnsaved：

```tsx
<MemoryPage key={user.id} userId={user.id} markdown={markdown}
  resumeName={profile?.name || '职得offer'} disabled={busy || loggingOut || !persistence.loaded}
  onLoad={(loaded, meta) => update(previous => ({ ...previous,
    profile: loaded, source_text: loaded.raw_text || '', source_name: meta.name || '已保存经历库',
    markdown: '', page: 'workbench',
  }))} />
```

3. B 如需工作台按钮，可调用 `downloadMarkdown(markdown, name)` 和 `await downloadWord(markdown, name)`（来自 `frontend/src/lib/export.ts`）；务必捕获错误并展示，禁止空稿导出。
4. PDF 尚未实现。Word 路由已接入；下载失败明确报错，不回退生成伪造文件。

## 验收边界
本轮前端测试 166 项、相关后端测试 50 项；测试使用虚构资料与临时数据库，不调用外部模型。DOCX 检查正文、字体、A4 和分页规则；实际 Word 软件分页和当前版本浏览器布局尚未人工验收。

## 经历库维护
- 可重命名选中记录；可将当前工作台事实更新到该记录，或另存为新记录。更新前明确确认，保存不改变工作台确认状态。
- PATCH /api/profiles/{id} 接收 name、可选 profile、expected_revision；revision 来自最新详情。版本冲突返回 409，重新查看后再决定；所有写入按服务端账户隔离并要求 CSRF。
- 点击载入先展示替换确认；取消不改变材料、JD 或正文，确认后原子替换材料、撤销事实确认并清空旧稿。
- Word 使用 A4、中文字体、标题随正文及孤行控制；仍需用户检查实际分页，不保证一页。

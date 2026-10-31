# 角色 D 验收与交接记录

日期：2026-10-31。基线：0c40af9。本轮所有演示资料均为虚构，无真实模型调用。

## 已完成与验证

- MemoryPage：列表、详情、载入确认、确认删除、失败重试、空态；载入产生独立副本并撤销确认。严格校验旧资料结构，账户切换/卸载忽略迟到响应。
- Markdown：当前正文原样下载，文件名清理、空稿阻止、下载地址释放。
- Word：新增 POST /api/export/docx，返回 A4 DOCX；中文字体、标题、段落、列表与常用行内格式。PDF：新增 POST /api/export/pdf，返回 A4 PDF；复用登录/CSRF、空稿、大小、非法字符、退出后拒绝、附件响应头及无远程关系契约，并检查中文字体缺失时的明确错误。
- 前端 `npm.cmd --prefix frontend test`：6 个测试文件、67 项通过（其中 D 新增 13 项）。页面测试执行实际处理器，未替代浏览器验收。
- `frontend/node_modules/.bin/tsc.cmd --project frontend/tsconfig.json`：通过，包含尚未接入 App 的 MemoryPage。
- `npm.cmd --prefix frontend run build`：通过；默认入口尚未引用 D 页面，因此该构建不代表页面导航已接通。
- `.venv/py310/Scripts/python.exe -m unittest tests.test_export tests.test_accounts tests.test_persistence tests.test_workbench_contract -v`：36 项通过。Word 5 项新增测试使用独立测试应用注册路由；账户/工作台/持久化使用原应用及临时数据库。

## 待负责人接入

严格按 [BEHAVIOR.md](BEHAVIOR.md) 将 MemoryPage 替换 App 的 memory-placeholder，并在 main.py 注册 api.export。本轮未修改 App.tsx、api.ts、工作台或主服务入口，没有新增依赖。默认主页面仍为原占位页，默认服务暂不提供 Word URL。

## 未验证与已知问题

- 未做真实浏览器的桌面/窄屏布局、主导航、下载、刷新后页面恢复及两账户整链路演示。
- DOCX 已由 python-docx 重读并检查 ZIP/OOXML；未用 Word/LibreOffice 渲染检查分页、字体替换或最终视觉效果，不能宣称排版已验收。
- 复杂 Markdown 表格、图片、HTML 为文本处理。Word/PDF 不抓取链接或图片，不保存生成文件。PDF 依赖部署环境可用的中文字体。
- 工作台图片输入：JPG/PNG/WebP 经过大小、格式和像素校验后交给视觉模型，返回结果仍需人工确认；未验证真实中文简历图片识别质量时，不宣称视觉解析稳定可用。
- 全量 unittest discovery 并未全绿：旧 tests/test_tool_loop.py 以无登录方式调用 profiles，5 条旧断言与现账户契约冲突，并在导入时 sys.exit。其余旧脚本也含导入即执行逻辑，不应将专项回归称作全量通过。未修改他人模块；建议 A 迁移该脚本到临时数据库、带 Cookie/CSRF 的新契约。
- 默认 Python 3.14 无法安装仓库固定的 pydantic-core 2.27.2；本轮在已安装的 Python 3.10 隔离环境完成测试。建议团队使用 Python 3.12 统一环境。

## A 接入后的演示步骤（待执行）

1. 按 README 启动，创建演示账户 A；输入 fixtures/role-d/materials.md 和 jd.md，解析后人工核对、确认并保存经历库。
2. 刷新并进入个人记忆；核对名称、时间、两段经历，查看详情。载入后应回工作台、原 JD 保留、旧稿清空且待重新确认。
3. 再次确认并生成，用 Markdown 和 Word 下载；检查文件正文一致、中文正常、分页无裁切。
4. 退出并创建账户 B，确认列表为空；用 A 的经历 ID 请求读取/删除应 404（自动化已验证）。
5. 返回账户 A；取消删除应不变，确认删除后刷新列表应消失。已载入工作台保持原状。
6. 模拟网络失败与恢复，检查错误提示、刷新重试和删除重试；用手机宽度确认无横向溢出。
7. 截图只展示虚构材料；录制后确认视频播放、仓库访问和最终提交材料。

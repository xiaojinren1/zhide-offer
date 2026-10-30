# 今晚开发契约（2026-10-30）

保留现有 FastAPI + React 工程，先完成本地单人验证骨架，明天按运行结果分工。应用名称统一为职得offer，页面参考蓝白三栏工作台设计。

## 本轮验收
- 一套明确的安装、启动和检查方式；后端健康检查及前端构建通过。
- 文本或文档解析为可编辑经历，编辑后撤销确认，用户明确确认后才可生成。
- 输入任意岗位 JD，使用真实模型接口生成 Markdown 简历；模型失败明确展示，不返回伪造成功结果。
- 工作台三栏：材料与JD、事实确认、简历预览；窄屏顺序排列。保留已有诊断、质检、面试入口。
- Markdown 导出可用。Word/PDF、图片、语音、普通账户及隔离、正式任务历史均不在本轮宣称完成。
- 当前经历文件存储尚无账户隔离，仅供负责人本机验证，不能当作正式多用户服务。
- 仅合成演示材料用于真实API验证；不发送现有用户文件。API key 留在服务端，不进入前端或日志。

## 冻结接口
POST /api/resume/parse-text {text} -> {ok,profile,raw_text,error?}
POST /api/resume/parse multipart file -> 同上
POST /api/resume/generate {jd_text,resume_profile,jd_keywords:[]} -> {ok,markdown,untraceable,traceability_passed,error?}
profile 包含 name,experiences,skills,education,raw_text,user_confirmed。
experiences 每条包含 kind,name,role,period,actions,results,skills。
确认只表示用户认可本次提供的事实，不等同于外部背调或真实性认证。

## 本轮工作边界
公共数据契约和接口由负责人统一。先复用解析、模型适配、规则检查；新建工作台，不重写全部业务。不推送代码或部署。完成后记录真实验证结果和明天剩余任务。

HTTP 错误：未确认/缺输入为422，未配置为503，生成未完成为504；FastAPI 返回 {detail:字符串}。其它业务失败保留 {ok:false,error:字符串}。前端需要同时展示两种错误格式。
# 真实联调补充契约

材料没有量化成果时，保留可验证的定性产出，不要求模型补数字或量级。质检应区分原始资料待补充项与生成稿错误；缺少量化仅作为人工补充建议，不能阻止基于已有事实生成简历。工具轮次结束时，模型应输出最终 Markdown 正文，不输出继续检查或修订的计划。

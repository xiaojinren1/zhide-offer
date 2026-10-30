param()
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '未找到项目Python环境，请按 RUNBOOK.md 完成安装。' }
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw '前端尚未构建，请先执行 npm.cmd --prefix frontend run build。' }
Write-Host '职得offer启动后，请打开 http://127.0.0.1:8000；按 Ctrl+C 停止。'
& $pythonPath (Join-Path $projectRoot 'backend\main.py')
exit $LASTEXITCODE

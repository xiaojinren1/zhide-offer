param()
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '未找到项目Python环境，请按 RUNBOOK.md 完成安装。' }
& $pythonPath (Join-Path $projectRoot 'start.py')
exit $LASTEXITCODE

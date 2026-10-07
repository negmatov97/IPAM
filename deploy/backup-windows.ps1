# IPAM zaxira nusxasi — Windows uchun (shu kompyuterda ishlatilganda).
# Vazifalar rejalashtiruvchisiga (Task Scheduler) qo'shish, har kuni 02:00 da:
#   schtasks /Create /TN "IPAM zaxira nusxa" /SC DAILY /ST 02:00 /F `
#     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"<loyiha papkasi>\deploy\backup-windows.ps1\""

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
Set-Location $project
& "$project\.venv\Scripts\python.exe" manage.py backup_db
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

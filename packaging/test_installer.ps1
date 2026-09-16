<#
安裝程式的端對端測試（CI 在乾淨的 Windows 上跑）：靜默安裝 → 用裝好的程式跑冒煙測試 → 靜默解除安裝。
不要在自己的電腦上跑：會安裝／移除真正的「台股分析」。
#>
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$env:PYTHONUTF8 = "1"

$Root = Split-Path -Parent $PSScriptRoot
$Version = (Get-Content (Join-Path $Root "build\version.txt") -Raw).Trim()
$Installer = Join-Path $Root "dist\TWStockAnalytics-Setup-$Version.exe"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\TWStockAnalytics"

Write-Host "==> 靜默安裝"
$p = Start-Process -FilePath $Installer -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=desktopicon" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "安裝失敗（exit code $($p.ExitCode)）" }

foreach ($path in @("python\pythonw.exe", "launcher.pyw", ".installed", "src\app.py", "ms-playwright")) {
    if (-not (Test-Path (Join-Path $InstallDir $path))) { throw "安裝後缺少 $path" }
}
$shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "台股分析.lnk"
if (-not (Test-Path $shortcut)) { throw "沒有建立桌面捷徑" }
Write-Host "[ok] 檔案與捷徑"

Write-Host "==> 用安裝好的程式跑冒煙測試"
& (Join-Path $InstallDir "python\python.exe") (Join-Path $PSScriptRoot "smoke_test.py") $InstallDir
if ($LASTEXITCODE -ne 0) { throw "安裝後冒煙測試失敗" }

Write-Host "==> 靜默解除安裝"
$uninstaller = Join-Path $InstallDir "unins000.exe"
$p = Start-Process -FilePath $uninstaller -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "解除安裝失敗（exit code $($p.ExitCode)）" }
Start-Sleep -Seconds 3  # 解除安裝程式會再啟動一個行程刪除自己
if (Test-Path (Join-Path $InstallDir "src")) { throw "解除安裝後程式檔仍在" }
Write-Host "安裝程式測試全部通過"

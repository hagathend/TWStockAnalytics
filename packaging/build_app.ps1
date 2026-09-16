<#
組出「安裝版」的完整程式資料夾（build\app），之後交給 Inno Setup 包成安裝程式。

內容：
  python\          獨立版 Python 3.13（python-build-standalone，可整個資料夾搬移）＋鎖定版本的套件
  ms-playwright\   PDF 與新聞內文擷取用的 Chromium（headless shell）
  src\ scripts\ launcher.pyw .streamlit\ ...   程式本體，取自 git HEAD（只含版控中的檔案，不會帶到 data\ 或設定檔）
  .installed       安裝版標記，讓程式把資料放到 %LOCALAPPDATA%\TWStockAnalytics\data
  app.ico

用法（專案根目錄）：
  powershell -ExecutionPolicy Bypass -File packaging\build_app.ps1
#>
param(
    [string]$OutDir = "build",
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest 的進度條會讓下載慢十倍
# 打包機器（含 CI）的主控台編碼常是 cp1252，Python 印中文會直接當掉，強制用 UTF-8
$env:PYTHONUTF8 = "1"

$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root $OutDir
$App = Join-Path $Build "app"

# 固定版本 + 雜湊驗證，確保每次打包出來的 Python 都一樣、下載內容沒被竄改
$PythonUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.13.15%2B20260901-x86_64-pc-windows-msvc-install_only.tar.gz"
$PythonSha256 = "9bcc038a0bf180612ed56dec93d4977d035e80b8d9320ef51a38c287baf134b7"

function Invoke-Checked([string]$Description, [scriptblock]$Command) {
    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description 失敗（exit code $LASTEXITCODE）" }
}

if (git -C $Root status --porcelain) {
    Write-Warning "工作目錄有未提交的變更；打包只會使用已提交的 HEAD 內容"
}

New-Item -ItemType Directory -Force $Build | Out-Null
if (Test-Path $App) { Remove-Item -Recurse -Force $App }
New-Item -ItemType Directory -Force $App | Out-Null

# 1. 獨立版 Python（下載過且雜湊正確就沿用快取）
$Tarball = Join-Path $Build "python-standalone.tar.gz"
$needDownload = -not (Test-Path $Tarball)
if (-not $needDownload) {
    $needDownload = (Get-FileHash $Tarball -Algorithm SHA256).Hash.ToLower() -ne $PythonSha256
}
if ($needDownload) {
    Write-Host "==> 下載獨立版 Python"
    Invoke-WebRequest -Uri $PythonUrl -OutFile $Tarball
}
$actual = (Get-FileHash $Tarball -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $PythonSha256) { throw "Python 壓縮檔雜湊不符：$actual" }
Invoke-Checked "解壓縮 Python" { & "$env:SystemRoot\System32\tar.exe" -xzf $Tarball -C $App }
$Python = Join-Path $App "python\python.exe"

# 2. 套件（鎖定版本）
Invoke-Checked "安裝套件" {
    & $Python -m pip install --disable-pip-version-check --no-warn-script-location --no-cache-dir `
        -r (Join-Path $Root "requirements.lock")
}

# 3. Chromium：程式只用無頭模式，裝 headless shell 就好（比完整 Chromium 小很多）
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $App "ms-playwright"
Invoke-Checked "安裝 Chromium" { & $Python -m playwright install --only-shell chromium }
Remove-Item Env:\PLAYWRIGHT_BROWSERS_PATH

# 4. 程式本體：只取 git 追蹤中的檔案
$SourceZip = Join-Path $Build "source.zip"
Invoke-Checked "匯出程式碼" {
    git -C $Root archive --format=zip -o $SourceZip HEAD `
        src scripts launcher.pyw .streamlit/config.toml LICENSE README.md requirements.lock
}
Expand-Archive -Path $SourceZip -DestinationPath $App -Force

$Version = (& $Python -c "import sys; sys.path.insert(0, r'$App'); from src.version import __version__; print(__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) { throw "讀取版本號失敗" }
Set-Content -Path (Join-Path $App ".installed") -Value $Version -Encoding ascii -NoNewline
Set-Content -Path (Join-Path $Build "version.txt") -Value $Version -Encoding ascii -NoNewline

Invoke-Checked "產生圖示" { & $Python (Join-Path $PSScriptRoot "make_icon.py") (Join-Path $App "app.ico") }

# 5. 防外洩檢查：絕不能把個人資料、設定檔、金鑰打包進去
$forbidden = Get-ChildItem -Path $App -Recurse -Force -File | Where-Object {
    $_.FullName -notlike "$App\python\*" -and $_.FullName -notlike "$App\ms-playwright\*" -and (
        $_.Name -like "*.db" -or $_.Name -like "*settings.json" -or $_.Name -eq ".env" -or
        $_.Name -eq "watchlist.json" -or $_.FullName -like "$App\data\*")
}
if ($forbidden) { throw "打包內容含有不應發布的檔案：$($forbidden.FullName -join ', ')" }

Get-ChildItem -Path $App -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 6. 用打包出來的 Python 實際跑一次
if (-not $SkipSmokeTest) {
    Invoke-Checked "冒煙測試" { & $Python (Join-Path $PSScriptRoot "smoke_test.py") $App }
}

$sizeMb = [math]::Round(((Get-ChildItem $App -Recurse -Force -File | Measure-Object Length -Sum).Sum / 1MB), 0)
Write-Host "完成：$App（版本 $Version，$sizeMb MB）"

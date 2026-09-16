<#
把 build\app 包成安裝程式 dist\TWStockAnalytics-Setup-<版本>.exe。先執行 build_app.ps1。

需要 Inno Setup（https://jrsoftware.org/isinfo.php）。新版 Inno Setup 內建繁體中文介面；
舊版沒有的話，會改下載固定版本並驗證雜湊的官方翻譯檔。
#>
param([string]$OutDir = "build")

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root $OutDir
$App = Join-Path $Build "app"
$Dist = Join-Path $Root "dist"

$LanguageUrl = "https://raw.githubusercontent.com/jrsoftware/issrc/6ef32198ef1f7b7b375cd4b6b90896c2a58eb4c2/Files/Languages/ChineseTraditional.isl"
$LanguageSha256 = "031684fc769259291fd563338b5abe20b7753c88ab5a2976b83a80788deb8455"

if (-not (Test-Path (Join-Path $App ".installed"))) { throw "找不到 $App，請先執行 packaging\build_app.ps1" }
$Version = (Get-Content (Join-Path $Build "version.txt") -Raw).Trim()

$candidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }
if (-not $candidates) { throw "找不到 Inno Setup 的 ISCC.exe，請先安裝 Inno Setup" }
$Iscc = @($candidates)[0]
Write-Host "==> 使用 $Iscc"

$languageArg = @()
$bundled = Join-Path (Split-Path $Iscc) "Languages\ChineseTraditional.isl"
if (-not (Test-Path $bundled)) {
    $languageFile = Join-Path $Build "ChineseTraditional.isl"
    Write-Host "==> 這版 Inno Setup 沒有內建繁體中文，下載官方翻譯檔"
    Invoke-WebRequest -Uri $LanguageUrl -OutFile $languageFile
    $actual = (Get-FileHash $languageFile -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $LanguageSha256) { throw "翻譯檔雜湊不符：$actual" }
    $languageArg = @("/DLanguageFile=$languageFile")
}

New-Item -ItemType Directory -Force $Dist | Out-Null
& $Iscc /Qp "/DAppVersion=$Version" "/DBuildDir=$App" "/DOutputDir=$Dist" @languageArg (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup 編譯失敗（exit code $LASTEXITCODE）" }

$installer = Join-Path $Dist "TWStockAnalytics-Setup-$Version.exe"
$sizeMb = [math]::Round((Get-Item $installer).Length / 1MB, 0)
Write-Host "完成：$installer（$sizeMb MB）"

; 台股分析 Windows 安裝程式（Inno Setup）
;
; 由 packaging\build_installer.ps1 呼叫，會帶入 AppVersion / BuildDir / OutputDir。
; 設計重點：
;   - 不需要系統管理員權限，裝在 %LOCALAPPDATA%\Programs\TWStockAnalytics
;   - 資料在 %LOCALAPPDATA%\TWStockAnalytics\data，不在程式資料夾裡，更新與重裝都不會動到
;   - 更新＝直接執行新版安裝程式：先關掉執行中的程式，再清掉舊程式檔重新放入
;   - 解除安裝預設保留資料，詢問後才刪

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\build\app"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef LanguageFile
  #define LanguageFile "compiler:Languages\ChineseTraditional.isl"
#endif

#define AppName "台股分析"
#define TaskName "TWStockAnalytics 每日收集"

[Setup]
AppId={{6B0F3E0A-8C1D-4B5E-9A7F-2D4C6E8B1A35}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=hagathend
AppPublisherURL=https://github.com/hagathend/TWStockAnalytics
AppSupportURL=https://github.com/hagathend/TWStockAnalytics/issues
AppUpdatesURL=https://github.com/hagathend/TWStockAnalytics/releases
DefaultDirName={localappdata}\Programs\TWStockAnalytics
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=TWStockAnalytics-Setup-{#AppVersion}
SetupIconFile={#BuildDir}\app.ico
UninstallDisplayIcon={app}\app.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=no

[Languages]
Name: "zhtw"; MessagesFile: "{#LanguageFile}"

[Tasks]
Name: "desktopicon"; Description: "在桌面建立捷徑"; GroupDescription: "其他選項："

[InstallDelete]
; 更新時先清掉舊的程式檔，避免已刪除的舊檔案殘留（資料不在這裡，不受影響）
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\ms-playwright"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; Description: "立即開啟{#AppName}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName '{#TaskName}' -Confirm:$false -ErrorAction SilentlyContinue"""; Flags: runhidden; RunOnceId: "RemoveDailyTask"

[Code]
{ 關掉從這個程式資料夾執行中的 python（App 伺服器、背景下載、排程收集），否則檔案被占用無法更新或移除 }
procedure StopRunningApp();
var
  ResultCode: Integer;
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  if not DirExists(AppDir) then
    exit;
  Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process python,pythonw -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -like ''' + AppDir + '\*'' } | Stop-Process -Force"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningApp();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  DataDir := ExpandConstant('{localappdata}\TWStockAnalytics');
  if not DirExists(DataDir) then
    exit;
  { 預設「否」：靜默解除安裝（/SUPPRESSMSGBOXES）時也會保留資料 }
  if SuppressibleMsgBox('要一併刪除收集的資料嗎？' + #13#10#13#10 +
      '包含股市歷史資料、我的持股紀錄與各項設定。' + #13#10 +
      '選「否」會保留，之後重新安裝可以直接繼續使用。',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    DelTree(DataDir, True, True, True);
end;

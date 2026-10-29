; Zealous インストーラー(Inno Setup)。GitHub Actions で ZealousSetup.exe を作る。
; 管理者権限なしでユーザーごとにインストールし、「設定 > アプリ」からアンインストールできる。
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8C1B2F0E-5A7D-4E8B-9C3F-2A6D1E4B7F90}
AppName=Zealous
AppVersion={#AppVersion}
AppPublisher=Zealous
DefaultDirName={localappdata}\Programs\Zealous
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ZealousSetup
SetupIconFile=..\assets\zealous.ico
UninstallDisplayIcon={app}\Zealous.exe
UninstallDisplayName=Zealous
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作る"
Name: "autostart"; Description: "PC起動時に自動で起動する"; Flags: unchecked

[Files]
Source: "..\dist\Zealous\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Zealous"; Filename: "{app}\Zealous.exe"
Name: "{autodesktop}\Zealous"; Filename: "{app}\Zealous.exe"; Tasks: desktopicon
Name: "{userstartup}\Zealous"; Filename: "{app}\Zealous.exe"; Tasks: autostart

[Run]
; 初回はセットアップ画面(Ollama・VOICEVOX・AIモデル・音声認識の自動準備)が開き、終わると本体が起動する
Filename: "{app}\Zealous.exe"; Description: "Zealous を起動する"; Flags: postinstall nowait skipifsilent
; アップデート(静かなインストール)の後は自動で起動し直す
Filename: "{app}\Zealous.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
; 動作中の Zealous / Ollama / VOICEVOX を止め、部品と設定を消すか確認する
Filename: "{app}\Zealous.exe"; Parameters: "--uninstall"; RunOnceId: "ZealousCleanup"; Flags: waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
; 自動起動を設定画面から作った場合のショートカット
Type: files; Name: "{userstartup}\Zealous.lnk"

[Code]
// 動いている Zealous(会話のための裏方のプロセスも含む)を止めてから入れ替える。
// 止まらずにファイルが使用中のままだと、途中で「変更を元に戻しています」となりインストールが中止される。
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code, I: Integer;
begin
  for I := 1 to 3 do
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM Zealous.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Sleep(700);
  end;
  Result := '';
end;

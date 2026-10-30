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
; 使用中ファイルの自動検出(Restart Manager)は、ファイル数が多いと準備に時間がかかるので使わず、
; [Code] の PrepareToInstall で Zealous を止める
CloseApplications=no
; インストールの記録を %TEMP% の「Setup Log ～.txt」に残す(失敗したときの原因調べ用)
SetupLogging=yes

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
// (/T は付けない: アップデートではこのインストーラー自身が Zealous から起動されており、一緒に止めてしまうため)
// 止まらずにファイルが使用中のままだと「DeleteFile エラー: コード5」や「変更を元に戻しています」となる。
function PowerShell(Script: String): Integer;
var
  Code: Integer;
begin
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
          '-NoProfile -NonInteractive -WindowStyle Hidden -Command "' + Script + '"',
          '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Result := Code
  else
    Result := -1;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  // Zealous と部品(Ollama・VOICEVOX)を止め、本当に終わる(ファイルが手放される)まで待つ。1回の PowerShell で行う(速くするため)。
  // 部品も止める: Zealous のフォルダの部品(msvcp140.dll など)を使っていることがあり、動いたままだと上書きできない。
  // まず名前で絞って止め(速い)、最後に場所で全体を確かめる(名前の分からないものも止める)。
  Code := PowerShell('$app=''' + ExpandConstant('{app}') + '\*''; $data=''' + ExpandConstant('{localappdata}') + '\Zealous\*''; '
    + '$ours = { param($list) $list | Where-Object { $_.Path -and ($_.Path -like $app -or $_.Path -like $data) } }; '
    + '$p = & $ours (Get-Process -Name Zealous,ollama*,run,VOICEVOX*,engine -ErrorAction SilentlyContinue); '
    + '$p | Stop-Process -Force -ErrorAction SilentlyContinue; $p | Wait-Process -Timeout 15 -ErrorAction SilentlyContinue; '
    + '$rest = & $ours (Get-Process); '
    + 'if ($rest) { $rest | Stop-Process -Force -ErrorAction SilentlyContinue; $rest | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue; '
    + 'Start-Sleep -Milliseconds 300; if (& $ours (Get-Process)) { exit 1 } }; exit 0');
  Log('Zealous と部品の残り確認: ' + IntToStr(Code));
  if Code = 1 then
    Result := 'Zealous を終了できませんでした。' + #13#10 +
              'タスクマネージャー（Ctrl+Shift+Esc）で「Zealous」「ollama」「run」をすべて終了してから、' +
              'もう一度インストールしてください。終了できない場合は、PCを再起動してからインストールしてください。';
end;

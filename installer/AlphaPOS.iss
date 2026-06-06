; Inno Setup script for the Alpha POS installer.
; Build steps (on a Windows box):
;   1. .venv\Scripts\pyinstaller AlphaPOS.spec            -> dist\AlphaPOS\
;   2. "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\AlphaPOS.iss
;      -> installer\Output\AlphaPOS-Setup.exe   (the single .exe you give the client)
;
; The client runs ONE file. It accepts the Terms on the license page, picks an
; install folder, and the app installs. All Python is compiled into the bundle
; (no readable source on disk). On first Start the app sets up its database,
; admin account and static files automatically. Business data (DB, settings,
; logs) lives per-user under %LOCALAPPDATA%\AlphaPOS and survives upgrades.

#define AppName "Alpha POS"
#define AppVersion "1.0.0"
#define AppPublisher "Alpha POS"
#define AppExeName "AlphaPOS.exe"
#define AppId "{{8F3A1C2E-7B44-4E2D-9A1F-1A2B3C4D5E6F}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\AlphaPOS
DefaultGroupName=Alpha POS
DisableProgramGroupPage=yes
DisableWelcomePage=no
AllowNoIcons=yes
LicenseFile=..\desktop\tos.txt
OutputDir=Output
OutputBaseFilename=AlphaPOS-Setup
SetupIconFile=..\desktop\AlphaPOS.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline dialog
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The whole PyInstaller one-folder output (exe + compiled bytecode + DLLs).
Source: "..\dist\AlphaPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Alpha POS"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall Alpha POS"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Alpha POS"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Alpha POS now"; Flags: nowait postinstall skipifsilent

[Code]
{ On uninstall, offer to remove the per-user business data. Default keeps it
  (a reinstall then picks up the same database) — deleting is opt-in. }
procedure CurUninstallStepChanged(CurStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\AlphaPOS');
    if DirExists(DataDir) then
    begin
      if MsgBox('Also delete all Alpha POS business data (database, settings, logs) at:'
        + #13#10 + DataDir + #13#10 + #13#10
        + 'Choose No to keep it for a future reinstall.',
        mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;

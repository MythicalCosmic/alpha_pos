; Inno Setup script for the Alpha POS installer.
; Build steps (on a Windows box):
;   1. .venv\Scripts\pyinstaller AlphaPOS.spec        -> dist\AlphaPOS\
;   2. Compile this script with Inno Setup (iscc installer\AlphaPOS.iss)
;      -> Output\AlphaPOS-Setup.exe  (the single .exe you give the customer)
;
; The .exe installs the app, the user accepts the ToS in the GUI on first run,
; everything (DB migrations, admin, static) is set up automatically the first
; time they press Start.

#define AppName "Alpha POS"
#define AppVersion "1.0.0"
#define AppPublisher "Alpha POS"
#define AppExeName "AlphaPOS.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\AlphaPOS
DefaultGroupName=Alpha POS
DisableProgramGroupPage=yes
OutputBaseFilename=AlphaPOS-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The whole PyInstaller one-folder output.
Source: "..\dist\AlphaPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Alpha POS"; Filename: "{app}\{#AppExeName}"
Name: "{userdesktop}\Alpha POS"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Alpha POS"; Flags: nowait postinstall skipifsilent

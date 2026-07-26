#define AppName "S Talking"
#ifndef AppVersion
#define AppVersion "0.17.2-rc2"
#endif
#ifndef SourceDir
#define SourceDir "..\..\dist\S-Talking"
#endif
#ifndef OutputDir
#define OutputDir "..\..\artifacts\package\installer"
#endif
#ifndef OutputBaseFilename
#define OutputBaseFilename "S-Talking-0.17.2-rc2-setup"
#endif

[Setup]
AppId={{BD8A7352-0C93-4C2E-ACD7-7F3F5C8AA221}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=S Talking
DefaultDirName={autopf}\S Talking
DefaultGroupName=S Talking
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\S-Talking.exe
SetupIconFile=..\..\app\resources\brand\app-icon.ico
PrivilegesRequired=lowest

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\S Talking"; Filename: "{app}\S-Talking.exe"
Name: "{autodesktop}\S Talking"; Filename: "{app}\S-Talking.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\S-Talking.exe"; Description: "Launch S Talking"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

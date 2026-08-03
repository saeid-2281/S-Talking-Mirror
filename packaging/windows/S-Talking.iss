#define AppName "S Talking"
#ifndef AppVersion
#define AppVersion "0.18.2-rc1"
#endif
#ifndef SourceDir
#define SourceDir "..\..\dist\S-Talking"
#endif
#ifndef OutputDir
#define OutputDir "..\..\artifacts\package\installer"
#endif
#ifndef OutputBaseFilename
#define OutputBaseFilename "S-Talking-0.18.2-rc1-setup"
#endif
#define AppIcon "..\\..\\app\\resources\\brand\\official\\S-Logo.ico"

[Setup]
AppId={{BD8A7352-0C93-4C2E-ACD7-7F3F5C8AA221}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=S Talking
AppPublisherURL=https://github.com/saeid-2281/S-Talking-Mirror
AppSupportURL=https://github.com/saeid-2281/S-Talking-Mirror/issues
AppUpdatesURL=https://github.com/saeid-2281/S-Talking-Mirror/releases
DefaultDirName={localappdata}\Programs\S Talking
DefaultGroupName=S Talking
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
UninstallDisplayIcon={app}\S-Talking.exe
UninstallDisplayName=S Talking {#AppVersion}
SetupIconFile={#AppIcon}
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
ChangesAssociations=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\S Talking"; Filename: "{app}\S-Talking.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\S Talking"; Filename: "{app}\S-Talking.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\S Talking"; ValueType: string; ValueName: "InstallVersion"; ValueData: "{#AppVersion}"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\S Talking"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty

[Run]
Filename: "{app}\S-Talking.exe"; Description: "Launch S Talking"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

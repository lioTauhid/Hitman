; Inno Setup script for the Hitman Windows installer (requires Inno Setup 6.3 or later).
; Normally run by `make package` / `python scripts/build.py --package`, which passes the defines below.
; To run it by hand after `make build`:  iscc /DAppVersion=0.1.0 scripts\hitman.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Hitman"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef OutputName
  #define OutputName "Hitman-" + AppVersion + "-windows-x64-setup"
#endif
#ifndef IconFile
  #define IconFile "..\build\hitman.ico"
#endif

[Setup]
; Keep AppId unchanged forever: it is how Windows recognises upgrades of the same app.
AppId={{17EA43DA-4192-4299-83C1-0AB8DB24117B}
AppName=Hitman
AppVersion={#AppVersion}
AppVerName=Hitman {#AppVersion}
AppPublisher=Hitman
AppPublisherURL=https://github.com/lioTauhid/Hitman
AppSupportURL=https://github.com/lioTauhid/Hitman/issues
AppUpdatesURL=https://github.com/lioTauhid/Hitman/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\Hitman
DefaultGroupName=Hitman
DisableProgramGroupPage=yes
; Installs for the current user without an admin prompt; the user can choose "all users" instead.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Hitman.exe
UninstallDisplayName=Hitman
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; The AppUserModelID matches the one the app sets, so pinned and running windows share one taskbar icon.
Name: "{autoprograms}\Hitman"; Filename: "{app}\Hitman.exe"; AppUserModelID: "Hitman.Hitman"
Name: "{autodesktop}\Hitman"; Filename: "{app}\Hitman.exe"; AppUserModelID: "Hitman.Hitman"; Tasks: desktopicon

[Run]
Filename: "{app}\Hitman.exe"; Description: "{cm:LaunchProgram,Hitman}"; Flags: nowait postinstall skipifsilent

; Collections and settings live in %APPDATA%\Hitman and are kept on uninstall, so reinstalling keeps them.

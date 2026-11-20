; Inno Setup script: one-file Windows installer. Installs per user (no admin rights, no UAC prompt).
; User data lives in %LOCALAPPDATA%\NTULineBot, so upgrades and uninstalls never delete it.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
[Setup]
AppId={{B6C2D2A4-5E0C-4B1E-9C77-3F5A0A5D8E11}
AppName=NTU Nursing LINE Bot
AppVersion={#AppVersion}
DefaultDirName={autopf}\NTULineBot
DefaultGroupName=NTU Nursing LINE Bot
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
OutputDir=..\dist
OutputBaseFilename=NTULineBot-Setup
UninstallDisplayName=NTU Nursing LINE Bot

[Files]
Source: "..\dist\NTULineBot\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\NTU Nursing LINE Bot"; Filename: "{app}\NTULineBot.exe"
Name: "{autodesktop}\NTU Nursing LINE Bot"; Filename: "{app}\NTULineBot.exe"

[Run]
Filename: "{app}\NTULineBot.exe"; Description: "Start NTU Nursing LINE Bot now"; Flags: nowait postinstall skipifsilent

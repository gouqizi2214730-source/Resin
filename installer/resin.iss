; Resin 智能代理池网关 — Inno Setup 标准 Windows 安装包脚本 (仅打包 --onedir 目录版)

#define MyAppName "Resin 智能代理池网关"
#define MyAppExeName "Resin.exe"
#define MyAppPublisher "Resin Project (Localized Edition)"
#define MyAppURL "https://github.com/gouqizi2214730-source/Resin"
#ifndef MyAppVersion
  #define MyAppVersion "1.1.0"
#endif

[Setup]
AppId={{8D6B4A2E-5F19-4E3A-9C7B-2A1E9F4D8C31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\Resin
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=Resin-Setup-win64
SetupIconFile=..\assets\resin.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Resin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\resin.ico"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\resin.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; Instalador de Windows (Inno Setup 6).
; Lo llama build/build_windows.py con los valores de la build:
;   ISCC /DAppVersion=1.0.0 /DArch=x64 /DMinWin=10.0 /DSourceDir=dist\nuitka\main.dist
;        /DOutputDir=dist\release /DOutputName=NetworkTool-7.4.0-win-x64-setup build\installer.iss
; Un instalador por línea y arquitectura: win-x64 (MinWin 10.0), win7-x64 y win7-x86
; (MinWin 6.1sp1; la x86 sirve también en Windows 10/11 de 32 bits).

#define AppName      "NetworkTool"
#define AppExe       "NetworkTool.exe"
#define AppPublisher "EstebanKZL"
#ifndef AppVersion
  #define AppVersion Trim(FileRead(FileOpen("..\VERSION")))
#endif
#ifndef Arch
  #define Arch "x64"
#endif
#ifndef MinWin
  #define MinWin "6.1sp1"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\nuitka\main.dist"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\release"
#endif
#ifndef OutputName
  #define OutputName "NetworkTool-" + AppVersion + "-win-" + Arch + "-setup"
#endif

[Setup]
AppId={{B4C88E4C-B2BF-4A16-9BA6-94ADF7909FC7}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/EstebanKZL/NetworkTool
AppSupportURL=https://github.com/EstebanKZL/NetworkTool/issues
AppUpdatesURL=https://github.com/EstebanKZL/NetworkTool/releases
AppContact=89585806+EstebanKZL@users.noreply.github.com
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
#if Arch == "x64"
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif
; win: Windows 10 o más nuevo (PySide6). win7: Windows 7 SP1 o más nuevo (PySide2).
MinVersion={#MinWin}
CloseApplications=yes
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: postinstall nowait skipifsilent

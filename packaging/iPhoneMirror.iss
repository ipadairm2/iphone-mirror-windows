; Inno Setup 6 installer script for iPhone Mirror (per-user install, no admin required)
#define AppName "iPhone Mirror"
#define AppVersion "1.0.1"
#define AppPublisher "iPhone Mirror Contributors"
#define AppURL "https://github.com/0xCodez/iphone-mirror-windows"
#define AppExeName "iPhoneMirror.exe"
#ifndef AppSourceDir
  #define AppSourceDir "..\dist\iPhoneMirror"
#endif
#ifndef AppOutputDir
  #define AppOutputDir "..\dist"
#endif

[Setup]
AppId={{7D9B8431-5A4C-4F91-B7D4-0E27B8E4C102}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={localappdata}\Programs\iPhone Mirror
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#AppOutputDir}
OutputBaseFilename=iPhoneMirror-Setup
SetupIconFile=iPhoneMirror.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=iPhoneMirror.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{userprograms}\iPhone Mirror.lnk"
Type: files; Name: "{userdesktop}\iPhone Mirror.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  OneDriveShortcut: String;
  ProfileDir: String;
begin
  if CurStep = ssInstall then
  begin
    ProfileDir := GetEnv('USERPROFILE');
    if ProfileDir <> '' then
    begin
      OneDriveShortcut := ProfileDir + '\OneDrive\Desktop\iPhone Mirror.lnk';
      if FileExists(OneDriveShortcut) then
        DeleteFile(OneDriveShortcut);
    end;
  end;
end;

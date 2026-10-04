; Inno Setup – δημιουργεί το OTDRBatchReport-Setup-<έκδοση>.exe
; Build: iscc /DAppVersion=1.0.0 installer\setup.iss  (μετά το pyinstaller)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6E2C1B7A-3F4D-4B8E-9C11-0A7E5D2F9B31}
AppName=OTDR Batch Report
AppVersion={#AppVersion}
AppPublisher=OTDR Batch Report
DefaultDirName={autopf}\OTDR Batch Report
DefaultGroupName=OTDR Batch Report
OutputDir=..\dist
OutputBaseFilename=OTDRBatchReport-Setup-{#AppVersion}
SetupIconFile=..\otdr_report\icon.ico
UninstallDisplayIcon={app}\OTDRBatchReport.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Languages]
; Μόνο αγγλικά: το Inno Setup 6.7 δεν έχει πλέον επίσημο Greek.isl (το ίδιο το πρόγραμμα είναι στα ελληνικά)
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\OTDRBatchReport\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\OTDR Batch Report"; Filename: "{app}\OTDRBatchReport.exe"
Name: "{group}\{cm:UninstallProgram,OTDR Batch Report}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\OTDR Batch Report"; Filename: "{app}\OTDRBatchReport.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OTDRBatchReport.exe"; Description: "{cm:LaunchProgram,OTDR Batch Report}"; Flags: nowait postinstall skipifsilent

; Inno Setup – δημιουργεί το GrandwayBatchReport-Setup-<έκδοση>.exe
; Build: iscc /DAppVersion=2.1.0 installer\setup.iss  (μετά το pyinstaller)

#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif

[Setup]
AppId={{6E2C1B7A-3F4D-4B8E-9C11-0A7E5D2F9B31}
AppName=Grandway Batch Report
AppVersion={#AppVersion}
AppPublisher=Grandway Batch Report
DefaultDirName={autopf}\Grandway Batch Report
DefaultGroupName=Grandway Batch Report
UsePreviousGroup=no
OutputDir=..\dist
OutputBaseFilename=GrandwayBatchReport-Setup-{#AppVersion}
; εικονίδιο του Setup.exe: το ίδιο icon.ico με το exe (από το program_icon.png, tools/make_icon.py)
SetupIconFile=..\otdr_report\icon.ico
UninstallDisplayIcon={app}\GrandwayBatchReport.exe
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

[InstallDelete]
; Μετονομασία από «OTDR Batch Report» (≤ 1.1.0): σβήνονται το παλιό exe και οι παλιές συντομεύσεις
Type: files; Name: "{app}\OTDRBatchReport.exe"
Type: files; Name: "{autodesktop}\OTDR Batch Report.lnk"
Type: filesandordirs; Name: "{autoprograms}\OTDR Batch Report"

[Files]
Source: "..\dist\GrandwayBatchReport\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Ίδιο AppUserModelID με το πρόγραμμα (app.py), ώστε η γραμμή εργασιών να δείχνει το εικονίδιο του exe
Name: "{group}\Grandway Batch Report"; Filename: "{app}\GrandwayBatchReport.exe"; IconFilename: "{app}\GrandwayBatchReport.exe"; AppUserModelID: "GrandwayBatchReport.App"
Name: "{group}\{cm:UninstallProgram,Grandway Batch Report}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Grandway Batch Report"; Filename: "{app}\GrandwayBatchReport.exe"; IconFilename: "{app}\GrandwayBatchReport.exe"; AppUserModelID: "GrandwayBatchReport.App"; Tasks: desktopicon

[Run]
Filename: "{app}\GrandwayBatchReport.exe"; Description: "{cm:LaunchProgram,Grandway Batch Report}"; Flags: nowait postinstall skipifsilent

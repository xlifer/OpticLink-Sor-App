; Inno Setup – δημιουργεί το GrandwayBatchReport-Setup-<έκδοση>.exe
; Build: iscc /DAppVersion=3.5.2 installer\setup.iss  (μετά το pyinstaller)

#ifndef AppVersion
  #define AppVersion "3.5.2"
#endif

[Setup]
AppId={{6E2C1B7A-3F4D-4B8E-9C11-0A7E5D2F9B31}
AppName=Grandway Batch Report
AppVersion={#AppVersion}
AppPublisher=Grandway Batch Report
DefaultDirName={autopf}\Grandway Batch Report
DefaultGroupName=Grandway Batch Report
; Αναβάθμιση στη θέση της προηγούμενης έκδοσης (ίδιο AppId): ίδιος φάκελος, μία εγγραφή στις Εφαρμογές
UsePreviousAppDir=yes
UsePreviousGroup=no
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
AppVerName=Grandway Batch Report {#AppVersion}
CloseApplications=yes
RestartApplications=no
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
; Τα αρχεία του προγράμματος της προηγούμενης έκδοσης σβήνονται πριν μπουν τα νέα, ώστε να μη μένουν
; αρχεία που καταργήθηκαν. Ρυθμίσεις (μητρώο), διορθώσεις (%APPDATA%), .sor και PDF δεν είναι εδώ.
Type: filesandordirs; Name: "{app}\_internal"
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

[Code]
{ Αν το πρόγραμμα είναι ανοιχτό (και παλιές εκδόσεις, π.χ. 2.1.0), ζητείται να κλείσει πριν συνεχίσει.
  Σε σιωπηλή εγκατάσταση η απάντηση είναι «Cancel»: η εγκατάσταση σταματά χωρίς να αλλάξει τίποτα. }
function IsAppRunning(): Boolean;
var
  Locator, Service, Procs: Variant;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Procs := Service.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name = ''GrandwayBatchReport.exe''');
    Result := Procs.Count > 0;
  except
    Result := False;
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  while IsAppRunning() do
  begin
    if SuppressibleMsgBox('Grandway Batch Report is running.' + #13#10#13#10 +
         'Please close it and click OK to continue the update, or Cancel to exit Setup.',
         mbError, MB_OKCANCEL, IDCANCEL) <> IDOK then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

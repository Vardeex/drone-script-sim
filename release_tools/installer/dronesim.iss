; Instalator Drone Script Simulator (Inno Setup 6).
;
; Buduje go ``release_tools/build_installer.py`` - nie trzeba uruchamiać
; kreatora. Skrypt przekazuje dwie dyrektywy:
;
;   ISCC.exe /DSourceDir=<rozpakowana paczka> /DAppVersion=0.4.0 dronesim.iss
;
; Instalacja **dla bieżącego użytkownika, bez uprawnień administratora**:
; program trafia do ``%LOCALAPPDATA%\Programs\DroneSim``, a dane użytkownika
; (loty, własne sceny, ustawienia) do ``%LOCALAPPDATA%\DroneSim`` - poza
; katalogiem programu, żeby aktualizacja i deinstalacja ich nie kasowały.
; Instalator zapisuje ten katalog w ``launcher.json`` obok ``DroneSim.exe``,
; skąd czyta go launcher.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\portable-package"
#endif
; Edycja wydania: "" (standardowa) albo "for_potatoes" (słabe komputery).
; Instalator for_potatoes instaluje się OBOK standardowego: inny AppId, inny
; katalog programu i inna nazwa w „Aplikacjach i funkcje”, ale te same dane
; użytkownika (%LOCALAPPDATA%\DroneSim).
#ifndef Edition
  #define Edition ""
#endif

#if Edition == "for_potatoes"
  #define AppName "Drone Script Simulator for_potatoes"
  #define AppShortName "DroneSim for_potatoes"
  #define AppId "{{2B8F6C14-53D9-4F0A-8E27-C1A4B9D7E512}"
  #define OutputName "DroneSim-Setup-" + AppVersion + "-for_potatoes"
#else
  #define AppName "Drone Script Simulator"
  #define AppShortName "DroneSim"
  #define AppId "{{6F1C3B52-8E4A-4D1E-9C3B-7A5D2E8F0A11}"
  #define OutputName "DroneSim-Setup-" + AppVersion
#endif

#define AppPublisher "Vardeex"
#define AppExeName "DroneSim.exe"
#define ProjectDir "..\.."

[Setup]
; AppId musi zostać ten sam w kolejnych wersjach - po nim Windows rozpoznaje
; aktualizację (instalacja nowszej wersji na starszą bez deinstalacji).
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} - instalator
VersionInfoProductName={#AppName}
DefaultDirName={localappdata}\Programs\{#AppShortName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; bez administratora: instalacja per-użytkownik
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; aktualizacja: zamknij działającą aplikację, ale nie restartuj jej z automatu
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
AllowNoIcons=yes
OutputDir={#ProjectDir}\dist
OutputBaseFilename={#OutputName}
SetupIconFile={#ProjectDir}\release_tools\assets\dronesim.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "Utwórz skrót na pulpicie"; \
    GroupDescription: "Dodatkowe ikony:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; przy aktualizacji nie mieszaj plików starej i nowej wersji
Type: files; Name: "{app}\{#AppExeName}"
Type: filesandordirs; Name: "{app}\_launcher"
Type: files; Name: "{app}\launcher.json"
Type: files; Name: "{app}\data-dir.txt"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Odinstaluj {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Uruchom {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; dane użytkownika usuwamy tylko po potwierdzeniu (patrz [Code])
Type: files; Name: "{app}\launcher.json"
Type: files; Name: "{app}\data-dir.txt"

[Code]
const
  DefaultDataDir = '{localappdata}\DroneSim';

var
  { katalog danych zapisany przy instalacji - czytany przed usunięciem plików }
  StoredDataDir: String;

{ Katalog danych: parametr /DATA=... (testy) albo %LOCALAPPDATA%\DroneSim. }
function DataDir(): String;
var
  Custom: String;
begin
  Custom := ExpandConstant('{param:DATA|}');
  if Custom <> '' then
    Result := Custom
  else
    Result := ExpandConstant(DefaultDataDir);
end;

{ Zamień ``\`` na ``\\`` - ścieżka Windows w JSON musi mieć escapowane ukośniki. }
function JsonPath(const Value: String): String;
var
  Index: Integer;
begin
  Result := '';
  for Index := 1 to Length(Value) do
  begin
    if Value[Index] = '\' then
      Result := Result + '\\'
    else
      Result := Result + Value[Index];
  end;
end;

{ launcher.json mówi DroneSim.exe, gdzie trzymać loty, sceny i config. }
procedure WriteLauncherConfig();
var
  Json: String;
begin
  Json := '{"data_dir": "' + JsonPath(DataDir()) + '"}';
  if not SaveStringToFile(ExpandConstant('{app}\launcher.json'), Json, False) then
    MsgBox('Nie udało się zapisać pliku launcher.json w katalogu programu.'
           + #13#10 + 'Dane użytkownika trafią do katalogu programu.',
           mbError, MB_OK);
  { ten sam katalog w prostym pliku tekstowym - czyta go deinstalator, żeby
    wiedzieć, co ewentualnie usunąć (parametr /DATA dotyczy tylko instalacji) }
  SaveStringToFile(ExpandConstant('{app}\data-dir.txt'), DataDir(), False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WriteLauncherConfig();
    ForceDirectories(DataDir());
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Folder: String;
  Delete: Boolean;
  Buffer: AnsiString;
begin
  if CurUninstallStep = usUninstall then
  begin
    { katalog danych zapisany przy instalacji (plik istnieje, dopóki nie
      usuniemy plików programu); LoadStringFromFile wymaga AnsiString }
    StoredDataDir := '';
    if FileExists(ExpandConstant('{app}\data-dir.txt'))
       and LoadStringFromFile(ExpandConstant('{app}\data-dir.txt'), Buffer) then
      StoredDataDir := Trim(String(Buffer));
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    if StoredDataDir <> '' then
      Folder := StoredDataDir
    else
      Folder := DataDir();
    if DirExists(Folder) then
    begin
      if UninstallSilent() then
        { tryb cichy: nie pytamy (nie może zawiesić CI), dane zostają, chyba że
          ktoś jawnie zażądał ich usunięcia parametrem /DELETEUSERDATA=1 }
        Delete := ExpandConstant('{param:DELETEUSERDATA|0}') = '1'
      else
        Delete := MsgBox('Usunąć także Twoje dane (loty, własne sceny, ustawienia)?'
                         + #13#10 + Folder + #13#10#13#10
                         + 'Jeśli chcesz zachować dane na przyszłość, wybierz „Nie”.',
                         mbConfirmation, MB_YESNO) = IDYES;
      if Delete then
        DelTree(Folder, True, True, True);
    end;
  end;
end;

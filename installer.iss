; ============================================================
;  BALLAB  -  Inno Setup 설치 스크립트
;  사용법:
;    1. Inno Setup 6.x 설치: https://jrsoftware.org/isdl.php
;    2. 먼저 build.bat 을 실행해 dist\BALLAB.exe 생성
;    3. 이 파일을 Inno Setup Compiler 로 열고 Build > Compile
;    4. Output\ 폴더에 BALLABSetup.exe 생성됨
; ============================================================

#define AppName      "BALLAB"
#define AppVersion   "1.0"
#define AppPublisher "광운대학교 생체역학 연구실"
#define AppExeName   "BALLAB.exe"
#define AppURL       ""

[Setup]
; 앱 식별 GUID - 절대 변경하지 마세요 (변경 시 덮어쓰기 설치 불가)
AppId={{A3F2C1D4-8E5B-4F7A-9C2D-1B3E6F0A8D92}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; 이전 버전 자동 업그레이드
CloseApplications=yes
CloseApplicationsFilter=*.exe
; 출력 설정
OutputDir=Output
OutputBaseFilename=BALLABSetup
SetupIconFile=assets\ballab_icon.ico
; 압축
Compression=lzma2/ultra64
SolidCompression=yes
; UI 설정
WizardStyle=modern
WizardResizable=no
; 관리자 권한 불필요 (현재 사용자 전용 설치 허용)
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "korean";  MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
  Description: "바탕화면에 바로가기 아이콘 만들기"; \
  GroupDescription: "추가 작업:";

[Files]
; PyInstaller 로 빌드된 단일 exe
Source: "dist\{#AppExeName}"; \
  DestDir: "{app}"; \
  Flags: ignoreversion

[Icons]
; 시작 메뉴
Name: "{group}\{#AppName}";                    Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} 제거";               Filename: "{uninstallexe}"
; 바탕화면 (선택)
Name: "{autodesktop}\{#AppName}";              Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; 설치 완료 후 바로 실행 옵션
Filename: "{app}\{#AppExeName}"; \
  Description: "{#AppName} 지금 실행"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 앱이 만드는 데이터 폴더는 남겨두고 exe만 삭제
Type: filesandordirs; Name: "{app}"

# BalanceAnalyzer 사용 가이드 (How-to / Usage Guide)

작업 흐름별 사용법. 각 항목은 메뉴 경로와 단계까지 한 곳에 담았습니다.
(메뉴 라벨은 실제 영어 UI 기준입니다.)

## C3D 파일 불러오기 (Load a C3D file)

C3D 모션캡처/포스플레이트 파일을 분석에 불러옵니다 (load / import / 열기 / 불러오기).

- 메뉴: **Analyze → Load C3D...** (단축키 **Ctrl+L**).
- 파일 선택 창에서 `.c3d` 파일을 고르면, Force plate 신호(Fz, Fx, Fy, COP)와 마커 3D 궤적이 읽혀 Analyze 탭에 표시됩니다.
- 여러 파일을 한 번에: **Analyze → Load folder...** — 폴더 안의 모든 C3D를 한꺼번에 불러옵니다(여러 파일 일괄 분석용).

불러온 뒤 Analyze 탭에서 신호 그래프와 3D 마커 뷰를 확인할 수 있습니다.

## 프로젝트 저장/열기 (.ballab project)

프로젝트는 데이터 + 분석 설정 + 결과를 하나로 묶은 `.ballab` 파일입니다 (save / open / 저장 / 열기 / 프로젝트).

- 새 프로젝트: **Analyze → New Project** (**Ctrl+N**).
- 열기: **Analyze → Open Project...** (**Ctrl+O**) → `.ballab` 선택.
- 저장: **Analyze → Save Project** (**Ctrl+S**). 다른 이름으로: **Save Project As...** (**Ctrl+Shift+S**).
- 저장하지 않은 변경이 있으면 종료 시 저장 여부를 묻습니다.

## 분석 파이프라인 만들기 (Analysis pipeline)

파이프라인은 신호 처리 단계를 순서대로 쌓은 레시피입니다. **목록의 순서 = 실행 순서**이며, 파생 데이터는 모두 파이프라인에서 나옵니다 (pipeline / steps / 단계 / 분석 절차).

Analyze 탭의 파이프라인 영역에서 "+" Add-step으로 단계를 추가합니다. 단계 종류:
- **Filter** — 저역통과 필터(예: 6 Hz)로 신호 잡음 제거. 컷오프 주파수·차수·대상 신호 지정.
- **Detect events** — 신호에서 사건 자동 감지(예: 발뒤꿈치 접지 HS, 발가락 이지 TO). 방식: 고정 프레임, 임계값 교차(threshold), 극값(peak/valley), 영점 교차(zero crossing), 전체 최대/최소.
- **Metric** — 구간 내 지표 계산(ROM=운동범위, 최대/평균, 시간차 등).
- **Normalize** — 0–100% 시간으로 정규화(보행 사이클별 곡선·앙상블).

각 단계는 추가 후에도 편집·순서변경·on/off가 가능합니다. 분석 범위(Range)는 슬라이더로 시작/종료 시점을 지정해 전체 또는 일부만 분석할 수 있습니다.

## Walk 프리셋으로 빠르게 시작 (Walk preset)

처음부터 단계를 쌓는 대신, 보행 분석용 완성 파이프라인을 한 번에 깝니다 (preset / 프리셋 / walk / 보행).

- Add-step 팝업의 첫 그룹("Quick start")에서 **Walk (treadmill)** 또는 **Walk (overground)** 선택.
- 깔리는 순서: 마커 필터 → 관절각 → HS/TO 이벤트 → 공간시간 지표(보폭, 보행속도) → 운동학 지표 → 정규화(+ 지면 force 있으면 운동역학).
- 깔린 모든 단계는 그대로 **편집 가능**합니다.

## 파이프라인 저장/불러오기 (Save/Load pipeline)

분석 절차(데이터 제외)만 따로 저장해 다른 파일에 재사용합니다 (pipeline json / 분석설정 저장).

- 저장: **Analyze → Save Pipeline...** → `.json`으로 저장.
- 불러오기: **Analyze → Load Pipeline...** → 저장한 `.json` 적용.

## 결과 내보내기 — Excel 또는 CSV (Export results)

분석 결과(지표)를 표 파일로 내보냅니다 (export / save results / 내보내기 / 결과 저장 / 엑셀 / CSV / 다운로드).

- 메뉴: **Analyze → Export results (Excel)...** (단축키 **Ctrl+E**).
- 내보내기 창에서:
  1. **Data**: 내보낼 지표를 체크(전체 선택 토글 가능).
  2. **Files**: 여러 파일을 불러온 경우 내보낼 파일 선택.
  3. **Destination**: 파일명·저장 위치 지정, **형식 선택(Excel .xlsx / CSV .csv)**.
- **Excel(.xlsx)** 로 내보내면 여러 시트가 만들어집니다:
  - **Results** — 한 행 = 한 파일, 지표가 열로 들어간 넓은 표.
  - **Summary** — 범위별 통계(개수 N, 평균, 표준편차 SD, 표준오차 SE).
  - **Files** — 파일별 정보(프레임 수, 분석 범위).
  - **Events** — 감지된 이벤트 목록(파일, 이벤트명, 프레임, 시간).
- **CSV(.csv)** 로 내보내면 "Folder, Condition, File, Range + 지표 열" 형식의 한 표로 저장됩니다.

(실시간 기록 데이터를 내보낼 때는 Record 모드에서 **Record → Export CSV...** 를 씁니다.)

## 여러 시험 결과 모으기 — Statistics (Aggregate results)

여러 파일/조건의 결과를 한 표로 모읍니다 (statistics / aggregate / 모으기 / 통계).

- Analyze에서 현재 결과 보내기: **Analyze → Send results → Statistics**.
- 이전에 내보낸 Excel 가져오기: **Statistics → Import results (Excel)...** ("Results" 시트를 읽음).
- 모인 표 비우기: **Statistics → Clear results**.
- Statistics 탭은 모은 행을 표로 보여줍니다(Folder, Condition, File, Range + 지표). 통계 검정(t-test/ANOVA 등)은 추후 추가 예정.

## 포스플레이트/모션캡처 실시간 기록 (Record)

힘판(force plate)이나 모션캡처에서 실시간으로 신호를 받아 기록합니다 (record / capture / 기록 / 녹화 / 실시간).

- 탭 열기: **Record → Show Record**.
- 신호원(Source) 선택: Kunwei 힘판 / Qualisys(QTM) / Demo. IP 입력 후 **Connect**.
- **Zero(영점)**: 현재 값을 0 기준으로 맞춤(tare).
- 기록 시간(Duration) 지정 후 **Record**로 시작/중지 → CSV로 저장(기본: `~/Documents/Balancelab/data/`).
- 채널 부호가 반대면 **Record → Recording axis...** 에서 채널별 Normal/Inverted로 보정(실시간·기록에만 적용, 불러온 파일엔 영향 없음).

## 설정 (Settings)

- **Settings → Theme → Light / Dark**: 앱 전체 밝은/어두운 테마.
- **Settings → Appearance...**: 3D 골격·마커 색, 그래프 곡선 색(COP/AP/ML/Fx/Fy/Fz), 그리드·선 굵기·마커 크기. Apply로 즉시 적용.
- **Settings → View...**: 3D 뷰 표시/숨김.
- **Settings → Normalize...**: COP 변위를 발 위치/크기로 정규화(토글).
- **Settings → AI Assistant (RAG)...**: AI 도우미가 연결할 RAG 서비스 URL 설정(기본 http://localhost:8000).

## AI 도우미 여닫기 (AI Assistant panel)

문헌·사용법 질문에 답하는 AI 패널을 켜고 끕니다 (AI assistant / 도우미 / 챗).

- **Help → AI Assistant** 토글 → 창 오른쪽에 패널이 나타나거나 사라집니다.
- 질문을 입력해 보냅니다. 영어로 물으면 영어로, 한국어로 물으면 한국어로 답합니다.
- 답 아래 출처가 표시되고, 논문은 DOI 링크를 클릭해 원문을 열 수 있습니다.
- 답이 안 나오면: 서버에서 RAG 서비스(serve.py)와 LM Studio가 켜져 있는지, 패널 상단이 "Connected"인지 확인하세요.

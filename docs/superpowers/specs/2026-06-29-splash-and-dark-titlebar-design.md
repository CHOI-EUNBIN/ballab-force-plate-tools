# 스플래시 화면 + 다크 타이틀바 설계

날짜: 2026-06-29

## 목표
1. 프로그램 시작 시 로고 스플래시(로딩) 화면을 띄운다.
2. OS 타이틀바를 앱 테마에 맞춰 다크/라이트로 바꾼다.
3. 앱 기본 테마(저장된 설정이 없을 때)를 다크모드로 한다.

## 결정 사항
- 스플래시: **로고만** 표시(메시지/스피너 없음). 표시 시간은 **메인창 준비될 때까지** — 따로 강제 지연 없음.
- 타이틀바: **앱 테마를 따라감**(다크 테마 → 다크 타이틀바). OS 창 버튼(최소화/최대화/닫기)은 그대로 유지(frameless 아님).
- 기본 테마: **dark** (QSettings에 저장된 값이 없을 때만 적용; 기존 사용자 설정은 보존).

## 구현

### 1. 스플래시 — `main.py`
- `QApplication` 생성 직후, `MainWindow` 생성 **전에** `QSplashScreen`을 로고 픽스맵으로 띄운다.
- 로고: `assets/ballab_icon_master_1024_transparent.png` 를 320px로 부드럽게 스케일.
- `WA_TranslucentBackground` + 투명 PNG → 배경 없이 로고만 떠 있는 형태. 시작 시 깜빡이는 흰 빈 창도 자연스럽게 가려짐.
- 흐름: `splash.show()` → `app.processEvents()` → `win = MainWindow(...)` → `win.show()` → `splash.finish(win)`.

### 2. 다크 타이틀바 — `ui/main_window.py`
- `_apply_titlebar_theme()` 추가: Windows에서 `ctypes`로 `dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE=20, dark)` 호출. 실패 시 구버전 속성 19로 폴백. Windows 외에는 no-op, 예외는 모두 무시.
- `__init__` 끝에서 1회 호출(=show 전에 적용 → 처음부터 다크로 그려짐).
- `apply_theme()`에서도 호출 → 런타임 테마 전환 시 타이틀바도 같이 바뀜.

### 3. 기본 테마 — `ui/main_window.py`
- `self._theme = self._qsettings.value("theme", "light") or "light"` → 기본값 `"dark"` 로 변경.

## 영향 범위
- 변경 파일: `main.py`, `ui/main_window.py` (2개).
- 비-Windows에서는 타이틀바 변경이 no-op이라 안전.

## 개정 (2026-06-29) — 두 줄 → 한 줄 커스텀 타이틀바
OS 타이틀바 줄 + 메뉴바 줄이 두 줄로 겹쳐 어색해, 한 줄로 합치는 커스텀 타이틀바로 전환.
DWM 캡션 색 지정 방식(위 2번)은 폐기하고 아래로 대체.

- **새 파일 `ui/custom_titlebar.py`**:
  - `TitleBar(QWidget)` — 한 줄에 `[아이콘][QMenuBar][여백][min][max][close]`. 배경 `BG_PANEL`.
    빈 영역 드래그 = `windowHandle().startSystemMove()`(Aero 스냅 지원), 더블클릭 = 최대화 토글.
  - `WindowButton` — min/max/close 글리프를 직접 페인트(테마색), 호버 배경 QSS(close=빨강).
  - Windows 네이티브 글루: `enable_frameless()`(WS_THICKFRAME+WS_CAPTION 재부여 + DWM 그림자),
    `handle_native_event()`(`WM_NCCALCSIZE`로 캡션 제거, `WM_NCHITTEST`로 6px 가장자리 리사이즈,
    `WM_GETMINMAXINFO`로 최대화 시 작업표시줄 안 가림). 비-Windows는 no-op.
- **`ui/main_window.py`**:
  - `Qt.FramelessWindowHint` 설정, 메뉴를 독립 `QMenuBar`로 빌드해 `TitleBar`에 넣고 `setMenuWidget()`로 상단 배치.
  - `showEvent`에서 1회 `enable_frameless()`, `nativeEvent`→`handle_native_event`, `changeEvent`로 max 버튼 글리프 동기화.
  - `_apply_titlebar_theme()`는 `TitleBar.apply_theme(palette)` 호출로 단순화(기존 DWM 캡션색 코드 제거).
- 테스트: 전체 679 passed / 30 skipped 유지.

# 시작 로고 애니메이션 (페이드 + 부드러운 확대) 설계

날짜: 2026-06-29

## 목표
프로그램 시작 시 뜨는 로고 스플래시를 정적 표시에서 **페이드 + 부드러운 확대** 애니메이션으로 바꿔
고급스러운 인상을 준다.

## 결정 사항
- **스타일**: 페이드 + 부드러운 확대. 로고가 투명→불투명으로 나타나면서 scale 0.92→1.0으로 살짝 커진다.
- **표시 시간**: 최소 0.8초 보장. 메인창이 더 빨리 준비돼도 최소 0.8초는 떠 있다가 페이드아웃.
- **로고만** 표시(메시지/스피너 없음). 기존 결정 유지.

## 핵심 문제
현재 `main.py`는 `win = MainWindow(...)`를 동기적으로 생성하며, 이 동안 이벤트 루프가 막힌다.
`QSplashScreen` 위에 애니메이션을 얹어도 빌드 중에는 프레임이 진행되지 않는다.
→ **이벤트 루프 기반으로 시작 흐름을 재구성**하는 것이 핵심.

## 구현

### 1. 새 컴포넌트 — `ui/splash.py` (신규)
`AnimatedSplash(QWidget)`:
- 창 플래그: `FramelessWindowHint | WindowStaysOnTopHint | Tool`(작업표시줄 미표시),
  속성 `WA_TranslucentBackground` → 배경 없이 로고만.
- 고해상도 원본 로고(QPixmap) 보유. 위젯 크기는 여유 있게(예: 360×360)라 확대해도 잘리지 않음.
- 화면 중앙에 배치.
- Qt 프로퍼티 2개:
  - `opacity`(float, 0.0→1.0) — setter에서 `update()` 호출.
  - `scale`(float, 0.92→1.0) — setter에서 `update()` 호출.
- `paintEvent`:
  - `QPainter`, `painter.setOpacity(self._opacity)`로 페이드.
  - `SmoothPixmapTransform` 켜고, 기준 로고 크기(예: 300px) × `self._scale` 만큼의 타겟 사각형을
    위젯 중앙에 두고 원본 픽스맵을 그린다(매 프레임 부드럽게 다운스케일).
- `start()`:
  - 인트로 애니메이션 시작 — `QPropertyAnimation`:
    - opacity 0→1, 700ms, `OutCubic`.
    - scale 0.92→1.0, 800ms, `OutCubic`.
  - 시작 시각 기록(`QElapsedTimer` 또는 시작 ms).
- `finish(win)` — **블로킹 없이** 최소 표시시간 보장:
  - 경과시간 계산 → `remaining = max(0, 800 - elapsed)`.
  - `QTimer.singleShot(remaining, self._outro)`.
  - `_outro`: 메인창을 앞으로 올리고(`win.raise_()`, `activateWindow()`),
    아웃트로 애니메이션(opacity 1→0, 350ms, `InCubic`) 재생 → 끝나면 `self.close()`.
- 애니메이션 객체는 멤버로 보관해 GC로 사라지지 않게 함.

### 2. 흐름 재구성 — `main.py`
기존:
```
splash.show(); processEvents(); win = MainWindow(...); win.show(); splash.finish(win); app.exec()
```
변경:
```
splash = AnimatedSplash(logo); splash.show(); splash.start()
def build():
    win = MainWindow(qtm_ip=args.ip)
    # win 참조 유지(클로저/리스트)
    win.show()                 # 스플래시 뒤에 표시
    if args.project ...: win.open_project_path(args.project)
    splash.finish(win)         # 최소시간 보장 + 아웃트로 + 공개
QTimer.singleShot(50, build)   # 이벤트 루프가 먼저 돌며 인트로가 그려지게
sys.exit(app.exec())
```
- `MainWindow` 생성을 `singleShot(50, ...)`으로 살짝 미뤄 인트로 첫 프레임들이 그려지게 한다.
  (빌드 중에는 루프가 막혀 인트로가 잠깐 멈췄다가, 빌드 후 재개 → 아웃트로.)
- 창 참조는 클로저 밖 변수에 담아 유지(가비지 컬렉션 방지).

### 3. 폴백
- 로고 PNG가 없거나 `isNull()`이면 스플래시를 만들지 않고 기존처럼 창만 바로 생성(현 동작 유지).

## 타이밍 값 (한 곳에 상수로)
| 단계 | 값 | easing |
|---|---|---|
| 인트로 페이드 | 0→1, 700ms | OutCubic |
| 인트로 확대 | 0.92→1.0, 800ms | OutCubic |
| 최소 표시 | 800ms | — |
| 아웃트로 페이드 | 1→0, 350ms | InCubic |

## 영향 범위
- 신규: `ui/splash.py`.
- 변경: `main.py`(시작 흐름 재구성, `QSplashScreen` → `AnimatedSplash`).
- 비교적 작고 국소적. 기존 다크 타이틀바/기본 테마 로직은 건드리지 않음.

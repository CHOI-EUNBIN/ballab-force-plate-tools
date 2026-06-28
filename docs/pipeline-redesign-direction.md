# Pipeline 섹션 재정립 — 방향 합의서 (@ui + @biomech)

> 작성 배경: "PIPELINE 섹션의 UI·구조가 전문 분석 프로그램 같지 않다. Event 섹션을 참고해
> 구조·프로세싱·용어·UI를 대대적으로 재정립하라."
> 이 문서는 biomech(과학적 구조·용어)와 ui(레이아웃·상호작용) 두 관점을 하나로 합친 **방향 합의서**다.
> 코드는 아직 변경하지 않았다. 착수 전 사용자 결정(맨 아래)을 먼저 받는다.

---

## 0. 한 줄 진단

현재 Pipeline의 본질 문제는 **이질적 단계(Filter·DetectEvent·Trajectory)가 역할 구분 없이 평면
한 줄 리스트로 섞여 있고, 정작 "분석"다운 단계(구간 분절·지표·정규화)가 통째로 빠져 있는 것**이다.
Event 하위시스템이 검증한 설계 원칙을 Pipeline에 그대로 이식하고, 백엔드에 **`stage`(역할) 차원을
비파괴적으로 더하면** 전문성을 즉시 얻으면서 초보자 친화(preset)와도 양립한다.

---

## 1. 두 관점의 수렴점 (회의 결과)

| 축 | biomech 결론 | ui 결론 | 합의 |
|---|---|---|---|
| 구조 | step에 `stage` 역할 차원 추가(평면 리스트는 유지) | 행을 타입별 배지/그룹으로 시각화 | **백엔드 `stage` 태깅 → UI가 stage로 배지·그룹·번호 렌더** |
| 키 | 이미 `PipelineStep.kind` 존재 | 배지/색을 `kind`로 매핑 가능 | 배지·그룹은 상위 개념인 **`stage`** 로 키잉(없으면 `kind` 폴백) |
| 용어 | derive/detect/segment/metric/normalize 5분류 | UI는 "kind→(배지,색,그룹) 매핑 테이블"만 필요 | 백엔드가 라벨 테이블 제공, UI는 표시만 |
| 범위 | metric·normalize가 빠져 "분석의 절반"만 표현 | 미구현 stage는 비활성 메뉴로 자리 표시 | 자리만 먼저 노출(전문 프로그램다움), 구현은 Phase 단계화 |

---

## 2. 백엔드 구조 — Event 모델에서 이식할 원칙 (biomech)

Event 하위시스템(`core/signals.py`, `core/events.py`, `core/events_compute.py`)이 잘 된 이유 =
Pipeline이 따라야 할 원칙:

1. **객체 종류 단방향 사슬**: `SIGNAL → EVENT → METRIC`. Event는 Signal을 읽고, Metric은 Event가
   만든 구간을 읽는다. 거꾸로 안 흐른다.
2. **순수 math ↔ dataset-glue 분리**: `core/events.py`(합성배열로 headless 테스트) ↔
   `core/events_compute.py`(Workspace glue). derive는 `signal_proc.py`(순수)에 이미 있음 →
   Pipeline은 *오케스트레이션만* 한다.
3. **detect-all-then-pick**: 검출기는 모든 인스턴스 반환, `select_instances`가 고름
   (`events.py:223`). "계산"과 "어디에 적용"을 분리.
4. **레시피 ↔ 데이터 분리 + 토큰 캐시**: step은 결과를 들지 않고 "무엇을 만들지"만 기술,
   결과는 Workspace에 lazy 캐시. 캐시 무효화는 토큰으로(`events_compute.py:33`).
   **색 등 cosmetic은 토큰에서 제외**(색만 바꿔도 재계산 없음) — metric/normalize에도 유지.
5. **모든 입출력은 catalog 키로**: detect input = `"fz" / "fz:filt" / "angle:Knee"`,
   Workspace가 필터링까지 해석. 새 stage도 동일 키 스킴으로 느슨하게 결합.
6. **forward-compat 폴백**: `from_dict`이 미지 step kind를 crash 없이 skip(`pipeline.py:340-345`),
   폴백은 raw. 새 stage 추가 때도 유지.

### 2-1. stage 표준 분류 (@researcher Visual3D 검증 완료)

라벨은 **영어**(Visual3D 관용어 기준). 내부 stage **키**는 `derive` 등 유지, **표시 라벨**만 분리(`STAGE_LABELS`).

| stage 키 | 표시 라벨(영어) | 만드는 객체 | 현재 매핑 | Visual3D 카테고리 | 상태 |
|---|---|---|---|---|---|
| `derive` | **Compute** | SIGNAL | `FilterStep`, `TrajectoryStep` | Signal / Model Commands | 있음(태깅만) |
| `detect` | **Detect Events** | EVENT | `DetectEventStep` | Event Commands | 있음(태깅만) |
| `segment` | **Segment** | CYCLE/구간 | 미구현 | (Event Sequence — 독립 카테고리 아님) | Phase C |
| `metric` | **Metric** | METRIC(값) | `metrics.py` 래핑 | Metric Commands | Phase C |
| `normalize` | **Normalize** | 0–100% 곡선 | 미구현 | Normalize Data | Phase C |

- derive 표시 라벨은 "Derive"가 아니라 **"Compute"**: Visual3D는 `Compute_Model_Based_Data` / Signal* 폴더로 신호를 "compute"한다("Derive"는 Visual3D 관용어 아님). 내부 키는 `derive` 유지.
- **segment는 Visual3D에 독립 카테고리가 없음** — "Event Sequence"(예: LHS→LHS)로 표현되어 Event/Metric command의 인자(`EVENT_SEQUENCE`)로 들어감. 우리는 cycle을 1급 객체로 노출하기로 했으므로 step 종류로는 유지하되, **구간은 metric/event step이 인자로 받는다**(구간 전용 stage가 신호를 잘라 만드는 게 아님).
- `FilterStep`·`TrajectoryStep`이 둘 다 derive → 배지 색 동일. Visual3D도 Signal Filter≠Signal Process로 폴더는 나누지만, 우리는 **2행 파라미터 요약**으로 구분(별도 배지 불필요).

> **⚠ 교정 (2차 @researcher Visual3D 검증, 사용자 반례 반영):** **stage는 실행 "순서 규칙"이 아니다.** 처음엔 `derive ≤ detect ≤ segment ≤ metric ≤ normalize` 고정 순서를 가정했으나, 사용자 시나리오(①Filter ②Detect ③각도 ④Min/Max ⑤각도Max로 다시 Detect = `Compute→Detect→Compute→Metric→Detect`)가 이를 깬다. Visual3D 파이프라인은 **위→아래로 실행되는 평면 명령 리스트**이고 command 카테고리는 **분류일 뿐 순서를 강제하지 않으며**, 같은 종류가 시퀀스 여러 위치에 등장할 수 있다(Event_Maximum/Threshold는 derived 신호·계산결과도 입력으로 받음 → metric→event 피드백 가능).
>
> 따라서:
> - **`stage`/`STAGE_ORDER` = UI 배지·분류·preset 묶음 라벨일 뿐, 실행 순서 규칙 아님.** 실행은 리스트의 물리적 순서.
> - **검증은 phase 순서가 아니라 "데이터(신호 존재) 의존성"** — `stage_order_warnings()` → **`data_dependency_warnings()`**: 각 step의 `requires()` 키가 그 줄 위에서 이미 `produces()`되었는지 누적 catalog로 검사. (구 Check 1=stage rank 폐기, Check 2=데이터 의존성 일반화.)
> - **각 step에 `produces()`/`requires()`(만드는/참조하는 catalog 키) 계약 신설** — lint과 Phase C step의 공통 기반.
> - **각도는 trial 전체로 계산**(`Compute_Model_Based_Data`엔 구간 인자 없음). 시나리오 ③+④는 "구간의 각도"가 아니라 **"각도 전체 계산 + 그 각도를 이벤트 구간(event_sequence)으로 reduce하는 Metric"**.
>
> 검증 근거: [Event_Maximum (derived/각도 입력, EVENT_SEQUENCE 인자)](https://wiki.has-motion.com/doku.php?id=visual3d:documentation:pipeline:event_commands:event_maximum), [Event_Threshold (계산·metric 결과로 event 생성, derived 신호는 위에서 먼저 compute)](https://wiki.has-motion.com/doku.php?id=visual3d:documentation:pipeline:event_commands:event_threshold), [Model Based Computations (각도=pipeline command, 전체 trial)](https://wiki.has-motion.com/doku.php?id=visual3d:tutorials:kinematics_and_kinetics:model_based_computations).

검증 근거(Visual3D 공식): [Pipeline Commands Reference](https://wiki.has-motion.com/doku.php?id=visual3d:documentation:pipeline:general_information:pipeline_commands_reference), [Lowpass Filter (Signal Filter folder)](https://wiki.has-motion.com/doku.php?id=visual3d:documentation:pipeline:signal_commands:lowpass_filter), [Metric Commands](https://c-motion.com/v3dwiki/index.php/Metric_Commands), [Plotting Normal Data (event sequence·51-pt normalize)](https://c-motion.com/v3dwiki/index.php/Tutorial:_Plotting_Normal_Data)

### 2-2. UI가 의존할 백엔드 계약

- **이미 충족**: `PipelineStep.kind`("filter"/"detect_event"/"trajectory") 존재
  (`core/pipeline.py:65,139,204`) → 타입 배지/색/그룹핑 즉시 가능.
- **(소량·비파괴) 추가 권장**:
  - `PipelineStep.stage` 클래스 속성 + `STAGE_ORDER` / `STAGE_LABELS` 상수 export.
  - `Pipeline.steps_by_stage() -> dict[stage, list[(index, step)]]` (원본 index 동반).
  - `pipeline.stage_order_warnings() -> list[(index, msg)]` (읽기 전용 경고).
- **(Phase 3 / UI thin화 후보)**: 표시 로직(`_pipeline_step_label`, 현재 UI에 박힘)을 core로 이전 —
  `step.display_name()` / `summary()` / `io_label()`. 과학 용어·신호 분류와 얽히므로 biomech 정의에 맞춰 core로.
  Filter "(filtered)" 출력 신호의 사람이 읽는 이름도 백엔드가 노출하면 "입력→출력" 행이 정확해짐.
- **불변 보장**: 빈 pipeline = raw, `from_dict(None)` 안전, 미지 kind skip, 색=cosmetic(토큰 제외) — 유지.

### 2-3. derive 통합(장기)

`FilterStep`(저역통과)·`TrajectoryStep`(2D 파생)은 본질적으로 **derive의 변종**이다. Event가
method(`threshold/peak/zero/frame`)를 한 step에 담듯, derive도 method(`lowpass/derivative/magnitude/cop_path`)를
담는 단일 `DeriveStep`으로 수렴하는 게 Visual3D식. **단 저장 포맷 영향이 커 engine 위임 + Phase 3.**
지금은 stage 태깅만으로 UI 전문화가 가능하므로 통합은 미룬다.

---

## 3. UI 구조 — Event 섹션에서 이식할 패턴 (ui)

### 3-1. 현재 UI 문제 (근거 `ui/analyze_tab.py`)
- 평면 QListWidget 한 줄 텍스트, 타입 시각 구분 없음(`:798-801`, `:2001-2008`).
- 헤더 +/▲/▼/✕ 4버튼 툴바형, 어느 행에 작용하는지 불명확(`:770-797`).
- 편집은 더블클릭 다이얼로그뿐, 행 hover 어포던스 없음(`:800-806`).
- 단계 번호·입력→출력 흐름 표시 없음. 파라미터가 한 줄에 우겨넣어져 김(`:2011-2032`).
- 활성/비활성 토글 없음. 빈 상태에 `empty_state.py` 미사용.

### 3-2. Events에서 이식할 것
- **2-필드 라벨 + 가운데점**: `"{이름} · {신호} {메서드}"` (`:4362-4365`) → "무엇/어떻게" 분리.
- **색 스와치를 1차 식별자로**(`_color_swatch :4331-4345`), raw key 대신 `label_for()` 사람이름.
- **`DetectEventStepDialog`의 `_form_group` 그룹화**(Basics/Detection/Guard/Result,
  `analyze_dialogs.py:355-443`) → 평면인 `FilterStepDialog`(`:75-175`)를 같은 격으로 승격.
- 메서드별 행 show/hide(`_sync_method_fields`), 단위 자동 동기화(`_sync_units`).

### 3-3. 제안 레이아웃 (사이드바 ≈ 220px)

```
┌─ ▾ PIPELINE ───────────────── [ + ] ─┐   ← 헤더: + 만 (▲▼✕ 제거)
│ ┌────────────────────────────────────┐│
│ │ ① │Compute│ COP filtering         ✎││  ← 번호배지 + stage배지(영어) + 이름 + hover
│ │   │       │ 10 Hz · Butterworth ·… ││  ← 2행: 파라미터 요약 (muted)
│ │   │       │ COP AP, COP ML → (filt) ││  ← 3행: 입력→출력 (선택)
│ ├────────────────────────────────────┤│
│ │ ② │Detect │ ●Heel Strike          ✎││  ← ● = 색 스와치 유지
│ │   │Events │ Fz threshold ↑ 20 N    ││
│ ├────────────────────────────────────┤│
│ │ ③ │Compute│ COP path              ✎││
│ └────────────────────────────────────┘│
│   ⠿ drag to reorder · toggle to skip   │
└────────────────────────────────────────┘

빈 상태: "No steps yet / Raw data is analyzed as-is / [ + Add step ]"
```

### 3-4. 구현 형태
- 평면 `QListWidget` 유지 + **`setItemWidget`으로 각 행에 커스텀 위젯**(번호배지·stage배지·2단 텍스트·hover ✎/토글).
  `QStyledItemDelegate`보다 단순하고 상호작용 위젯을 그대로 넣을 수 있음. `file-list` QSS 재사용.
- **순서 변경**: ▲▼ 제거 → 리스트 내부 드래그(InternalMove). *섹션 헤더 드래그
  `_enable_section_drag`(`:202-213`)와 충돌 주의 → 핸들 영역 분리.*
- **stage 배지 색**은 `style.py`에 `PIPELINE_STAGE_COLORS` dict로 모아 인라인 색 산재 금지.
- 추가/편집/재렌더 트리거(`_on_filter_changed`)·색 스와치·core 호출 계약은 **무변경**.

---

## 4. 전문성 ↔ 초보자 양립 (prime directive)

stage는 preset의 자연스러운 단위다 — 충돌하지 않는다.
- **Preset = stage별 step의 미리 채워진 묶음.** 예: "보행" = derive(저역통과) + detect(Fz→HS/TO) +
  segment(HS→HS) + metric(stance time, ROM) + normalize(0–100%). preset 한 번에 stage가 다 채워짐.
- **Progressive disclosure**: 기본은 "Gait analysis ✓" 한 줄 요약(초보자), "Advanced" 토글 시 개별 step 펼침(전문가).
- stage 표시 라벨은 영어(Compute/Detect Events/Segment/Metric/Normalize) — [[ui-labels-english]] 메모리.

---

## 5. 단계화(Phase) — 진행 상태

- **Phase A — ✅ 완료**: 백엔드 `stage` 태깅 + `STAGE_ORDER`/`STAGE_LABELS` + `steps_by_stage()` + `PipelineStep.enabled`.
  UI: `PipelineStepRow` 행 위젯(번호·stage 배지·2단 라벨·hover 편집/삭제·enable 토글), 헤더 `+`만, 빈 상태 카드.
- **Phase B — ✅ 완료**: `FilterStepDialog` 그룹박스 승격, 드래그 순서변경(섹션 드래그와 비충돌),
  enable 토글, 데이터 의존성 ⚠ 칩, `PIPELINE_STAGE_COLORS`.
- **교정 — ✅ 완료**: stage 고정 순서 폐기 → `data_dependency_warnings()`(produces/requires 누적 catalog 검사),
  STAGE_ORDER 의미 강등(표시 분류 라벨). 전체 **241 tests pass**.
- **Phase C — 설계 단계(아래 §6)**: `ComputeAngleStep`/`MetricStep`/`DetectEventStep(method=max/min)` +
  각도를 파이프라인 Compute step으로 승격 + 평면 시퀀스 실행기(Workspace 3-catalog) + 추가 UX를 팝업 다이얼로그로.

---

## 6. Phase C 설계 — 평면 시퀀스 + 신규 step 타입 (@engine 백엔드 설계안, @researcher Visual3D 검증)

목표: 사용자 시나리오 **①Filter → ②Detect → ③각도(전체) → ④Min/Max(metric) → ⑤각도Max로 Detect**
(= `Compute→Detect→Compute→Metric→Detect`)를 **평면 리스트**로 표현. 위→아래 실행하며 signal/event/metric 3개 catalog 누적.

> **🔑 핵심 원칙 (사용자 확정): 파이프라인이 모든 파생 데이터의 유일한 생성원.**
> raw(마커·force)만 입력이고, **각도·COP·필터·이벤트·지표 등 모든 파생 결과는 파이프라인 스텝을 추가·실행해야만 생성된다.** 자동 계산/암묵 폴백 **없음** — 각도 step이 없으면 각도는 존재하지 않는다. 스텝 파라미터(force 임계값 등)는 글로벌 설정이 아니라 **그 스텝 추가 다이얼로그 안에서 선택**한다. (메모리 "everything is a Signal" 통합 방향과 일치.)
> ⚠ 함의(초보자): 빈 프로젝트 = 파생결과 0 → **preset(보행/러닝/점프/균형)이 파이프라인을 자동으로 채워주는 것이 필수**(빈 화면 방지, beginner-first 직결).

### 6-1. 신규 step 스키마

**`ComputeAngleStep`** (stage=`derive`, 라벨 "Compute")
- model-based 관절각을 **trial 전체로** 산출(Visual3D `Compute_Model_Based_Data`엔 구간 인자 없음). 구간은 metric/event가 받음.
- 필드: `joints`(["Knee","Ankle","Hip"…] 또는 빈=전체), `enabled`. 계산식은 현 단일벡터각 단순화 유지.
- `produces() = {"angle:<Joint>" …}`, `requires()` = (결정필요) 빈 집합 vs marker 키.
- `to_dict={"kind":"compute_angle","joints":[…],"enabled":bool}`. glue `compute_angle_signals(workspace, joints)` 신설(events_compute 패턴).
- 마이그레이션: 현재 각도는 UI `_ensure_model_result`에 갇혀 전체 자동계산 → **step으로 완전 이전.** **폴백 없음**(스텝 없으면 각도 없음). 기존 Angle 토글 섹션은 "각도 생성"에서 손 떼고 "step이 만든 각도 표시"만 담당. 빈 화면은 preset이 ComputeAngleStep을 자동 주입해 방지.

**`ComputeCopStep`** (stage=`derive`, 라벨 "Compute") — 각도와 동일 원칙
- force-plate raw로부터 COP(압력중심)를 산출하는 스텝. 현재 COP가 자동 계산되던 것을 **스텝으로 이전**(각도와 마찬가지로 스텝 없으면 COP 없음).
- `produces()={"cop_ap","cop_ml",…}`(다중 force-plate면 `fp{n}:cop*`), `requires()`=force 채널. preset(균형)이 자동 주입.

**`MetricStep`** (stage=`metric`, 라벨 "Metric")
- 한 신호를 한 구간에서 스칼라로 reduce. 사용자 ④.
- 필드: `input`(signal_key 예 `"angle:Knee"`), `op`∈{max,min,mean,range,std,rms…}, `event_sequence`([start_label,end_label] 또는 None=전체), `name`, `enabled`.
- `produces()={"metric:<name>"}`, `requires()={input}` + (event_sequence 시) `{"event:start","event:end"}` → "각도 먼저 계산됐나/구간 이벤트 먼저 검출됐나" 자동 lint.
- `core/metrics.py`를 `op→함수` 테이블로 래핑, glue `core/metrics_compute.py`.
- **산출 형태(biomech 권고·Visual3D `Metric_Mean` 정합)**: 사이클별 배열을 1급 보존 + 요약 동시 산출 — `{"cycles": ndarray(N), "mean": float, "sd": float(ddof=1), "n": int, "unit": str}`. event_sequence=None이면 n=1. (Visual3D도 EVENT_SEQUENCE 위 range별 값 + `GENERATE_MEAN_AND_STDDEV`로 global mean/SD. 배열 보존이 표준 데이터모델.)
- op 집합은 Visual3D가 `Metric_Maximum/Minimum/Mean/Range/...` 별도 command인 것을 우리 규모에 맞춰 단일 step+op로 의식적 단순화.

**`DetectEventStep` method 확장** (stage=`detect`) — ⚠ @researcher 교정 반영
- 파생신호·metric을 입력으로 이벤트 생성(사용자 ⑤). `core/events.py`에 순수 검출함수 추가(합성 테스트).
- **명명 교정**: Visual3D `Event_Maximum`은 **국소 극값(=우리 `peak`)**이고, **전역 1점**은 `Event_Global_Maximum`이다. 따라서:
  - 구간 내 **전역 최대/최소 1점** → method **`global_maximum`/`global_minimum`** (Visual3D `Event_Global_Maximum/Minimum`).
  - 국소 극값 다수 → 기존 `peak`(= Visual3D `Event_Maximum`)로 충분.
  - "maximum=전역 1점"이라는 처음 표현은 명명 역전이었음 — 폐기.
- 점프 "착지 구간 내 최대 굴곡 1점"은 `global_maximum`(이벤트로) **또는** `MetricStep op=max`(스칼라로) 중 의도에 맞게. preset이 둘 중 무엇인지 명시할 것.
- `requires()`가 event_sequence/metric 참조를 인식하도록 확장.

**`NormalizeStep`** (stage=`normalize`, 라벨 "Normalize") — 사용자 확정: 정규화도 스텝
- **임의 신호를 0–100%로 시간정규화**하는 범용 스텝. 각도·force 등 어떤 입력이든 가능.
- 필드: `input`(signal_key — 예 `"angle:Knee"`, `"fz"`), `points`(기본 **101**), `event_sequence`(주기 구간 정의 — 예 HS→HS; 여러 주기면 ensemble), `enabled`.
- `produces()={"normalized:<input>"}`, `requires()={input}` + (event_sequence 시) 구간 이벤트 키. 다이얼로그에서 **입력 신호 + 포인트 수 + (선택)주기 이벤트**를 고른다(글로벌 설정 아님).
- 산출: ensemble 평균곡선 `(points,)` mean + sd(주기 여러 개일 때). MetricStep(스칼라)과 별개 산출물.

**파라미터 expression / metric 참조 (⚠ @researcher — 시나리오 ⑤ 결합 수단)**
- Visual3D는 `Event_Threshold`의 threshold 등 다수 파라미터를 **상수뿐 아니라 PROCESSED METRIC / expression**으로 받는다. 이것이 §2-1 "metric→event 피드백"의 실제 메커니즘.
- 따라서 DetectEventStep threshold(및 유사 수치 파라미터)는 **상수값 OR `metric:<name>` 참조**를 받아야 사용자 ⑤가 완성됨. Add 다이얼로그 폼에 "constant ↔ metric reference" 토글 필요.
- (선택) Visual3D `!`(파라미터 단위 "기본값 사용"·주석) 개념은 폼 UX 고려사항.

### 6-2. Workspace 실행 모델

현 Workspace(signal catalog만 lazy 캐시) → **3-catalog 확장**: signal(+`angle:*`) / event(라벨→프레임) / metric(이름→값|사이클배열).
`run_pipeline(workspace, pipeline)` 평면 리스트 1회 순회, kind별 compute glue 호출 결과를 catalog 누적,
다음 step이 `workspace.series("angle:Knee")`/`.events("HS")`/`.metric("knee_rom")`로 윗줄 산출물 참조.
빈 pipeline = raw 입력만 존재(각도·COP 등 파생결과 없음 — **폴백 없음**). 실행 모델 **eager 1-pass vs lazy**는 내부 구현 선택(권고 eager).

### 6-3. preset 4종 기본 구성 (@biomech, 문헌 근거 / @researcher Visual3D 검증)

> 차단주파수 분리: **마커용 FilterStep ≠ force/COP용 FilterStep**(별도 step, fs·대역 다름). ankle은 `_FE`만 metric/normalize에 사용(`_AB/_IE` low-reliability — [[ ]] foot/ankle frame 메모리). 정규화는 **101점**(Visual3D `/NORMALIZE_POINTS` 기본; ⚠ 처음 51점은 교정됨).

| preset | derive | detect | metric (op·event_sequence) | normalize |
|---|---|---|---|---|
| **gait** | 마커 6 Hz LP + `ComputeAngle([Hip,Knee,Ankle])`; fz raw | Fz threshold ↑20 N = **HS**, ↓20 N = **TO** | stance/stride time, Knee ROM=range, Peak knee flex=max, Hip ROM — 모두 **HS→HS** | **101점 O** |
| **run** | 마커 10–12 Hz LP + 하지 3각; fz raw | Fz threshold ↑20–50 N = **FC**, ↓ = **TO** | contact/flight time, Peak knee flex, Knee ROM — **FC→FC(stride)** | **101점 O** |
| **jump** | 마커 12–15 Hz LP + 하지 3각; fz raw | Fz ↓ = **Takeoff**, ↑ = **Landing**; 최대굴곡 = `global_maximum(angle:Knee)` 또는 `metric op=max` | Peak landing knee flex=max, ROM=range — takeoff/landing 구간 | **기본 X**(비주기) |
| **balance** | cop_ap/cop_ml 10 Hz LP (각도·이벤트 불필요) | **이벤트 없음**(정적 standing) | Prieto 13지표(path length, mean velocity, 95% ellipse area, RMS/Range AP·ML…) — **전체 trial** | **X** |

근거: Winter(보행 6 Hz), Bisseling & Hof 2006(빠른 동작 차단 상향), Scoppa 2013(COP 10 Hz), Perry *Gait Analysis*(HS→HS 주기), Prieto 1996(자세동요 13지표), C-Motion Normal Data(101점 ensemble).

**다중 사이클 집계**: 스칼라 metric = 사이클별 배열 + **mean±SD(ddof=1)** + n(+CV 권장). ensemble 평균곡선은 **NormalizeStep**(0–100%, 101점 점별 mean±SD)에서 별도 산출 — MetricStep(스칼라)과 NormalizeStep(곡선)은 다른 산출물.

### 6-4. Phase C UI 설계 (@ui)

- **통합 "Add step" 팝업 다이얼로그**(컨텍스트 메뉴 대체): 좌측 = 연산 카테고리 리스트(Compute▸Filter/Joint angles · Detect Events▸Threshold/Peak/Zero/Global max·min/Fixed · Metric▸Reduce · Compute path▸COP path), 우측 = `_FormGroup` 파라미터 폼 + 하단 **Produces/Requires 미리보기**. Add/Edit 같은 다이얼로그 재사용(Edit는 카테고리 잠금). `_add_*`/`_edit_*` 6개 → `_open_add_step()`/`_open_edit_step(i)` 2개로 수렴.
- **신규 step 행 표기**(2행 유지): ComputeAngle "Joint angles / Knee, Ankle, Hip", Metric "Knee ROM / range(angle:Knee) over HS→HS", Detect(global max) "●Peak flexion / global_max(angle:Knee)". Compute가 Filter·ComputeAngle 둘 다 → **이름줄 첫 단어로 구분**(배지 추가 없음). metric→event 피드백은 요약줄에 `op(input) over A→B`로 노출 + 선후 위반 시 기존 ⚠ 칩 자동.
- **각도 승격 ↔ Angle 섹션**: pipeline에 ComputeAngleStep 없으면 현행대로 전체 각도 자동 폴백; 있으면 그 step이 선언한 관절만 노출. Angle 토글 의미를 "각도 생성"→"생성된 각도 표시"로 좁힘. **가장 눈에 익은 부분이라 Phase C 마지막에** 전환.
- **백엔드 계약 요청**: `step.display_name()`/`summary()`(표시 로직 core 이전, UI thin화), `produces()/requires()` 노출, `available_detect_methods()`/`available_metric_ops()` 카탈로그 제공.

### 6-5b. 각도 부호 규약 — ✅ 확정 (@researcher ISB 검증, 사용자 결정)

**표준 = ISB/Grood-Suntay 정렬, 좌우 부호 통일(ML축 mirror).** 사용자 결정: V3D식 좌우 반대는 불편 → **양다리 통일**.

| 성분 | + 방향 | − 방향 | 좌우 |
|---|---|---|---|
| FE (시상면) | flexion | extension | 좌우 동일(원래 고정) |
| Ankle FE | dorsiflexion | plantarflexion | 좌우 동일 |
| AB (관상면, hip/knee) | abduction | adduction | **mirror로 통일** |
| Ankle 관상면 | inversion | eversion | **mirror로 통일** |
| IE (횡단면) | internal rotation | external rotation | **mirror로 통일** |

- 0° = 해부학적 중립(JCS 축 정렬); gait/run은 정적 standing offset 차감(`static_angle_offsets`).
- 좌우 통일 — ✅ **실측 검증·수정 완료**(257 tests). ⚠ ML축 반전만으로는 **FE만 통일되고 AB/IE/inv-ev는 좌우 반대로 남는 버그**가 있었음(S=diag(−1,1,1) conjugation은 ML축 회전부호만 보존). 수정: 왼쪽에서 **Cardan 축이 ML(x)이 아닌 성분만 negate**(회전순서 의존 — 하지 xyz/xzy=[FE,−AB,−IE]). 이제 abduction/internal-rot/inversion이 양다리 모두 +로 통일. `marker_model.py`의 `_left_sign_flip`/`left_negated_components`.
- 검증 산출물: `ANGLE_CONVENTION` 테이블 + `allow_peak_flexion_op(channel)`(FE만 True) + `standing_zero_selfcheck()`(정적 FE≈0 검사).
- preset op 핀 규칙: `peak flexion=max`는 **jcs FE 채널에만** 게이팅(헬퍼로 강제). vector(무부호) 채널·AB/IE는 제외. ankle은 dorsi=max·plantar=min 분리.
- 미해결 잔여: ankle `_AB`→inv/ev 라벨 정확화(관절별 임상용어), ankle "xzy" 순서가 FE 부호/0점에 주는 영향 실측.

### 6-5. 결정 사항 (사용자 확정 / 잔여)

**✅ 사용자 확정 — "모든 게 스텝, 파라미터는 스텝 다이얼로그 안에서":**
- **폴백 폐기**: angle/COP는 step 없으면 생성 안 됨(자동 계산·암묵 폴백 없음). 빈 화면은 preset이 스텝을 자동 주입해 방지.
- **force 임계값**: 글로벌 설정 아님 → force 기반 검출/계산 스텝 추가 시 **그 다이얼로그 안에서 선택**.
- **정규화**: `NormalizeStep`(stage=`normalize`)도 스텝. 어떤 신호(각도·force 등)든 입력으로 받고, **다이얼로그에서 입력 신호 + 포인트 수(기본 101) 선택**. 글로벌 "정규화 점수 설정" 없음.
- 함의: 모든 파생 파라미터는 스텝 다이얼로그에서 컨텍스트로 결정 → 글로벌 설정 페이지 최소화.

**잔여 결정:**
- **engine**: ① 실행 모델 **eager 1-pass vs lazy**(내부 구현 선택, 사용자 비노출 — 권고 eager), ② ComputeAngleStep `requires`에 marker 키 포함 여부(오탐 vs 정확성), ③ 사이클 간 집계 SD는 ddof=1.
- **제품**: 미지 kind skip 시 **데이터손실 경고** 띄울지(권고: 띄움).

> 관련 메모리: [[event-pipeline-redesign]], [[analysis-pipeline-unification]], [[beginner-first-ux]], [[ui-labels-english]], [[com-feature]]

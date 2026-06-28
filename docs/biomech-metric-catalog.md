# BalanceAnalyzer — 통합 생체역학 지표 카탈로그 (researcher, 2026-06-24)

동작 구분 없는 통합 카탈로그. biomech 구축 핸드오프 자료. 데이터요구: M=모션만, F=포스만, B=둘다, ID=역동역학(범위밖). 현황: ✅있음 / 🟡부분 / ❌없음.

## 핵심 결론
V3D = 2층(Signal-math 신호→신호, Metric 신호→스칼라). 우리는 골격(ComputeStep/MetricStep/DetectEventStep + cycle 분할 segment=[a,b] + mean±SD) 보유. **공백: ComputeStep에 normalize만(미분/적분/magnitude 없음), 시공간·impulse·loading rate·점프·대칭 op 전무.** 빌딩블록 3개(미분·적분·magnitude)면 절반 이상 열림.

## A. 시공간 (보행/러닝/트레드밀) — 대부분 `time_between_events` op 하나로 분해
- Stride time = t(HS₂)−t(HS₁) [s, B] ❌
- Step time = t(HS_ipsi)−t(HS_contra) [s] ❌
- Cadence = 60/step time [steps/min] ❌
- Stance time/% = TO−HS ; %=stance/stride [s,%] ❌
- Swing time/% = HS−TO ❌
- Double support = (RHS→LTO)+(LHS→RTO) ❌
- Contact time(run) = TO−HS [F] ❌ ; Flight time = HS−TO ❌
- Stride/step length = ‖pos(HS₂)−pos(HS₁)‖ AP [m, M] ❌ (위치차+magnitude)
- Speed = stride length/stride time ❌ ; Stride width = step벡터 외적 ML ❌

## B. 운동학 (전 동작)
- Joint ROM = max−min [deg] ✅(range/ANGLE_STATS)
- Peak angle = max|min ✅ ; Angle at event = value_at_event ✅
- 각속도 = 1차 central diff (x[i+1]−x[i−1])/(t[i+1]−t[i−1]) [deg/s] ❌ (derivative op)
- 각가속도 = 2차 central diff [deg/s²] ❌
- Peak 각속도 = max(|deriv|) ❌ ; Marker 속도/가속도 = 위치 미분 ❌

## C. 운동역학 (보행/러닝/점프)
- Peak vGRF = max(fz) [N] ✅ ; Peak vGRF %BW = max(fz)/BW 🟡(max+normalize)
- Impact/active peak = local peaks 🟡
- Loading rate (VALR) = peak/(t_peak−t_IC) [N/s] ❌
- vGRF impulse = ∫fz dt over HS→TO [N·s] ❌ (integrate op)
- Net vertical impulse(jump) = ∫(fz−BW)dt ❌
- Braking impulse = ∫fy⁻ dt (stance 음구간) ❌ ; Propulsive = ∫fy⁺ dt ❌
- Joint moment/power/work = 역동역학 [ID] ❌ **버릴 것**(모델 능력 밖)

## D. COP/균형 (균형/정적)
- RMS AP/ML, Range, Mean, MDIST, 95% Ellipse, Sway path, Mean velocity(+AP/ML), Sway area, MPF/MDF ✅ (COP_OPS 17, Prieto 1996)
- Sample/Approx entropy, convex-hull area ❌ **후순위/버릴 것**

## E. 점프 (CMJ/드롭점프)
- Jump height(flight-time) = g·t_flight²/8 [m] ❌ (flight time + 상수)
- Jump height(impulse) = v²/2g, v=∫(fz−BW)dt/m ❌
- Takeoff velocity = net impulse/mass ❌
- Contact time(drop) = TO−HS ❌ ; RSI = jump height/contact time ❌

## F. 대칭/변동성 (보행/러닝)
- Symmetry Index = (X_R−X_L)/(0.5(X_R+X_L))×100 [%] ❌ (전용 이항 op)
- Symmetry Ratio = X_R/X_L ❌ ; CV = SD/mean×100 🟡(per-cycle mean±SD 있음→1줄)

## 빌딩블록 분해 (3단: [신호변환]→[구간]→[축약])
```
각속도 peak     = derivative(angle) → cycle(HS→HS) → max
RFD/loading     = fz → cycle(HS→peak) → Δvalue/Δtime (또는 loading_rate op)
vGRF impulse    = fz → cycle(HS→TO) → integrate
braking impulse = fy → cycle(stance, fy<0) → integrate
stride time     = events → time_between_events(HS_i, HS_{i+1})
stance %        = time_between(HS,TO)/time_between(HS,HS)  [per-cycle ratio]
jump height(FT) = takeoff/landing → flight time → g·t²/8
resultant GRF   = magnitude(fx,fy,fz) → max
symmetry(stride)= stride_R, stride_L → symmetry_index op
```

## 우선순위
- **P1 빌딩블록**(core/signal_ops.py + ComputeStep 확장): derivative(order1/2, central diff, 비균일 dt), integral(cumtrapz + metric integrate), magnitude(√Σ). → 각속도/가속도/RFD/impulse/resultant/jump 임펄스 전부 열림.
- **P2 이벤트쌍 op**: time_between_events / frames_between_events → 시공간 전부. stance%/swing% = per-cycle 비율(segment 인프라 재사용). 별도 spatiotemporal 엔진 만들지 말 것.
- **P3 impulse 파생 + 점프**: vGRF impulse, braking/propulsive(부호 게이팅), loading_rate op, jump height/RSI.
- **P4 대칭/CV**: symmetry_index 전용 op(좌/우 metric 참조), CV(per-cycle SD/mean).

## 버릴 것
관절 모멘트/파워/work(역동역학), entropy/convex-hull, V3D Dot/Cross·마커 패턴 gait event, Eval_Expression(자유수식 파서 — beginner-first 충돌).

## 열린 결정 (biomech/사용자)
1. 미분 endpoint(forward/backward vs NaN) — V3D 미확인
2. 미분 전 필터 강제 여부(노이즈)
3. impulse 부호규약 + braking/propulsive 게이팅(integral sign_filter vs 별도 op), AP 전진=+ 확정
4. symmetry 공식(SI vs SR vs RI) 기본값
5. L/R 자동배정(Phase E) — HS_R/HS_L/TO_R/TO_L 라벨 컨벤션
6. 단위 추적표(deg→deg/s, N→N·s, magnitude 보존)
7. stride length: marker 1D축 신호 → magnitude로 X/Y/Z 조합 vs 전용 처리

## 출처
has-motion wiki: Metric Commands Overview / Temporal Distance Calculations for Gait / Compute Model Based Data / Automatic Gait Events. PMC3085638(braking/propulsive), PLOS One 0210000(loading rate), PMC6410267(jump/RSI), PMC10535875(symmetry), MDPI 8/4/158(CV).

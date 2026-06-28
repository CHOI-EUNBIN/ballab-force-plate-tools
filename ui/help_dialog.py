"""Help dialogs reached from the Help menu (metric reference)."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QWidget,
    QFrame, QPushButton, QDialogButtonBox,
)
from PyQt6.QtCore import Qt

from ui import style as S

# Each metric folds AP/ML into one entry. Text is bilingual (en/kr); the math
# formula (rich-text) is shared. AP/ML are noted in the "axes" line.
METRIC_DOCS = [
    {
        "cat": {"en": "Position & Excursion", "kr": "위치 · 변위"},
        "metrics": [
            {
                "name": "RMS", "unit": "mm",
                "desc": {
                    "en": "Root-mean-square of COP displacement around its mean — the typical sway amplitude. Larger means more sway.",
                    "kr": "평균 위치를 기준으로 한 COP 변위의 제곱평균제곱근 — 전형적인 흔들림 크기. 클수록 흔들림이 큽니다.",
                },
                "axes": {
                    "en": "AP: anterior–posterior axis · ML: medial–lateral axis",
                    "kr": "AP: 전후(앞뒤) 축 · ML: 좌우 축",
                },
                "formula": "RMS = &radic;( (1/n) &Sigma; (x &minus; x&#772;)<sup>2</sup> )",
            },
            {
                "name": "Range", "unit": "mm",
                "desc": {
                    "en": "Peak-to-peak COP excursion (max − min) within the window. Sensitive to brief outliers.",
                    "kr": "구간 내 최대−최소 COP 변위(peak-to-peak). 순간적인 이상치에 민감합니다.",
                },
                "axes": {"en": "Computed per axis (AP, ML)", "kr": "AP, ML 축별로 계산"},
                "formula": "Range = max(x) &minus; min(x)",
            },
            {
                "name": "Mean position", "unit": "mm",
                "desc": {
                    "en": "Average COP location in the window — describes posture / offset, not sway magnitude. Sign depends on the axis convention.",
                    "kr": "구간 내 평균 COP 위치 — 자세/오프셋을 나타내며 흔들림 크기는 아닙니다. 부호는 축 설정에 따라 달라집니다.",
                },
                "axes": {"en": "Computed per axis (AP, ML)", "kr": "AP, ML 축별로 계산"},
                "formula": "x&#772; = (1/n) &Sigma; x",
            },
        ],
    },
    {
        "cat": {"en": "COP signal & trajectory", "kr": "COP 신호 · 궤적"},
        "metrics": [
            {
                "name": "COP resultant distance (RD)", "unit": "mm",
                "desc": {
                    "en": "Instantaneous distance of the COP from its mean position (the sway centre) — the signal plotted as the 'COP' curve and used as the 'cop' event channel. The mean is subtracted, so it measures sway about the centre, not distance from the plate origin: a constant origin offset does not change it. Larger means the COP is momentarily farther from its centre.",
                    "kr": "COP가 자신의 평균 위치(흔들림 중심)로부터 떨어진 순간 거리 — 'COP' 곡선으로 그려지고 'cop' 이벤트 채널로 쓰이는 신호입니다. 평균을 빼므로 발판 원점이 아니라 흔들림 중심을 기준으로 한 동요를 나타냅니다(원점 오프셋이 바뀌어도 값은 그대로). 클수록 그 순간 COP가 중심에서 멀리 떨어져 있다는 뜻입니다.",
                },
                "axes": {
                    "en": "AP&#772;, ML&#772; = mean COP over the window; combines both axes into one resultant",
                    "kr": "AP&#772;, ML&#772; = 구간 평균 COP. 두 축을 합쳐 하나의 합성 거리로 만듭니다.",
                },
                "formula": "RD = &radic;( (AP &minus; AP&#772;)<sup>2</sup> + (ML &minus; ML&#772;)<sup>2</sup> )",
            },
            {
                "name": "Mean distance", "unit": "mm",
                "desc": {
                    "en": "Mean resultant distance (MDIST) — the average of the COP resultant distance RD over the window, i.e. the mean radius of sway about the centre. Larger means the COP sits farther from its centre on average (more sway). It is the arithmetic-mean companion of RMS, which is the quadratic mean of the same RD; MDIST &le; RMS always.",
                    "kr": "평균 합성 거리(MDIST) — 구간 동안 COP 합성 거리 RD의 평균으로, 흔들림 중심으로부터의 평균 반경입니다. 클수록 COP가 평균적으로 중심에서 멀리 떨어져 있다는 뜻(흔들림 큼)입니다. 같은 RD의 제곱평균인 RMS의 산술평균 짝이며, 항상 MDIST &le; RMS입니다.",
                },
                "axes": {
                    "en": "Combines AP & ML into one resultant (RD); AP&#772;, ML&#772; = window mean COP",
                    "kr": "AP·ML을 하나의 합성 거리(RD)로 결합. AP&#772;, ML&#772; = 구간 평균 COP",
                },
                "formula": "MDIST = (1/n) &Sigma; &radic;( (AP &minus; AP&#772;)<sup>2</sup> + (ML &minus; ML&#772;)<sup>2</sup> )",
            },
            {
                "name": "COP trajectory (statokinesigram)", "unit": "mm",
                "desc": {
                    "en": "The 2-D path of the COP in the ML–AP plane (x = ML, y = AP), drawn around the mean COP with the 95% confidence ellipse overlaid. Also called the statokinesigram. It is the spatial picture that the sway-path length and ellipse-area metrics summarise.",
                    "kr": "COP가 ML–AP 평면에서 그리는 2차원 경로(x = ML, y = AP)로, 평균 COP를 중심으로 그려지며 95% 신뢰 타원이 함께 표시됩니다. statokinesigram(통계운동도)이라고도 합니다. sway path length와 타원 면적 지표가 요약하는 공간 그림입니다.",
                },
                "axes": {
                    "en": "x = ML (medial–lateral), y = AP (anterior–posterior)",
                    "kr": "x = ML(좌우), y = AP(전후)",
                },
                "formula": "{ (ML[n], AP[n]) }",
            },
        ],
    },
    {
        "cat": {"en": "Spatial distribution", "kr": "공간 분포"},
        "metrics": [
            {
                "name": "95% Ellipse area", "unit": "mm²",
                "desc": {
                    "en": "Area of the 95% confidence ellipse fitted to the COP scatter — a compact 2-D measure of how widely the COP is distributed.",
                    "kr": "COP 산포에 맞춘 95% 신뢰 타원의 면적 — COP가 얼마나 넓게 분포하는지를 나타내는 2차원 지표.",
                },
                "axes": {
                    "en": "λ₁, λ₂ = eigenvalues of the AP–ML covariance · χ²(df=2, 0.95) ≈ 5.99",
                    "kr": "λ₁, λ₂ = AP–ML 공분산의 고유값 · χ²(df=2, 0.95) ≈ 5.99",
                },
                "formula": "A = &pi; &middot; &chi;<sup>2</sup><sub>0.95</sub> &middot; &radic;(&lambda;<sub>1</sub> &lambda;<sub>2</sub>)",
            },
        ],
    },
    {
        "cat": {"en": "Path & Velocity", "kr": "경로 · 속도"},
        "metrics": [
            {
                "name": "Sway path length", "unit": "mm",
                "desc": {
                    "en": "Total distance the COP traveled along its trajectory — accounts for the whole path, not just min-to-max. Occluded (missing) samples are skipped, so a single gap does not invalidate the whole path.",
                    "kr": "COP가 궤적을 따라 이동한 총 거리 — 최소-최대 거리가 아닌 전체 경로를 반영합니다. 결측(occlusion) 프레임은 건너뛰므로 한 군데 결측이 전체 경로 값을 무효로 만들지 않습니다.",
                },
                "axes": {"en": "", "kr": ""},
                "formula": "L = &Sigma; &radic;( &Delta;AP<sup>2</sup> + &Delta;ML<sup>2</sup> )",
            },
            {
                "name": "Mean velocity", "unit": "mm/s",
                "desc": {
                    "en": "Average COP speed (path length ÷ duration). Can be high even when the range is small, if the COP moves frequently. The resultant form uses the 2-D path; the AP and ML forms use the 1-D path along each axis (the total distance the COP moved in that single direction ÷ duration).",
                    "kr": "평균 COP 속도(경로 길이 ÷ 시간). 범위가 작아도 COP가 자주 움직이면 커질 수 있습니다. 합성(resultant)은 2차원 경로를, AP·ML 방향별은 해당 축 1차원 경로(그 한 방향으로 COP가 이동한 총 거리 ÷ 시간)를 사용합니다.",
                },
                "axes": {
                    "en": "Resultant (2-D path) or per axis (AP, ML 1-D path) · T = (n − 1) / fs",
                    "kr": "합성(2D 경로) 또는 축별(AP, ML 1D 경로) · T = (n − 1) / fs (분석 구간 길이)",
                },
                "formula": "v = L / T &nbsp;&nbsp; v<sub>AP</sub> = (&Sigma;|&Delta;AP|) / T &nbsp;&nbsp; v<sub>ML</sub> = (&Sigma;|&Delta;ML|) / T",
            },
            {
                "name": "Sway area", "unit": "mm²/s",
                "desc": {
                    "en": "Area swept by the COP per unit time (AREA-SW). Each consecutive pair of COP points forms a triangle with the mean COP; the summed triangle areas ÷ duration give the rate at which the COP encloses area. Larger means faster and/or wider 2-D sway. Unlike the 95% ellipse area it is a per-second rate that reflects how the COP actually moves, not just its scatter.",
                    "kr": "단위 시간당 COP가 쓸고 지나간 면적(AREA-SW). 연속한 두 COP 점이 평균 COP와 함께 삼각형을 이루며, 그 삼각형 면적의 합 ÷ 시간이 COP가 면적을 쓸어가는 속도입니다. 클수록 더 빠르고/넓은 2차원 흔들림을 뜻합니다. 95% 타원 면적과 달리 단순 산포가 아니라 COP가 실제로 어떻게 움직였는지를 반영하는 초당 비율입니다.",
                },
                "axes": {
                    "en": "AP&#772;, ML&#772; = window mean COP (triangles taken about the centre) · T = (n − 1) / fs",
                    "kr": "AP&#772;, ML&#772; = 구간 평균 COP(중심 기준 삼각형) · T = (n − 1) / fs",
                },
                "formula": "AREA-SW = (1/2T) &Sigma; | AP<sub>c</sub>[n+1]&middot;ML<sub>c</sub>[n] &minus; AP<sub>c</sub>[n]&middot;ML<sub>c</sub>[n+1] |",
            },
        ],
    },
    {
        "cat": {"en": "Kinematics (rate of motion)", "kr": "운동학 (운동 속도)"},
        "metrics": [
            {
                "name": "Peak angular velocity", "unit": "deg/s",
                "desc": {
                    "en": "The largest joint angular velocity (rate of angle change) in the window, keeping its sign. Computed by differentiating the joint angle once and taking the value farthest from zero. Larger means a faster joint movement (e.g. peak knee-flexion velocity in swing). Differentiation amplifies noise, so prefer a filtered angle as input; the result is reported at the frame of the extremum (an event).",
                    "kr": "구간 내 가장 큰 관절 각속도(각도 변화율)로 부호를 유지합니다. 관절각을 한 번 미분한 뒤 0에서 가장 먼 값을 취합니다. 클수록 관절이 빠르게 움직였다는 뜻입니다(예: 스윙기 무릎 굴곡 최대 각속도). 미분은 잡음을 키우므로 필터링된 각도를 입력으로 쓰는 것이 좋습니다. 극값이 발생한 프레임(이벤트)에서 보고됩니다.",
                },
                "axes": {
                    "en": "Per joint-angle channel; sign follows the angle's ISB convention. Channel labels are abbreviated by plane: F/E = flexion(+)/extension(&minus;), AB/ADD = abduction(+)/adduction(&minus;), IR/ER = internal(+)/external(&minus;) rotation; ankle uses Dorsi/Plantar (dorsiflexion+) and Inv/Ever (inversion+). L/R = body side.",
                    "kr": "관절각 채널별; 부호는 각도의 ISB 규약을 따름. 채널 라벨은 평면별 약어로 표기: F/E = 굴곡(+)/신전(&minus;), AB/ADD = 외전(+)/내전(&minus;), IR/ER = 내회전(+)/외회전(&minus;); 발목은 Dorsi/Plantar(배측굴곡+)·Inv/Ever(내번+). L/R = 좌/우.",
                },
                "formula": "&omega; = d&theta;/dt &nbsp; (np.gradient) &nbsp;&rarr;&nbsp; peak = &theta;'<sub>|max|</sub>",
            },
            {
                "name": "Peak angular acceleration", "unit": "deg/s²",
                "desc": {
                    "en": "The largest joint angular acceleration in the window, keeping its sign. Computed by differentiating the joint angle twice. Larger means a more abrupt change of angular velocity. Double differentiation strongly amplifies noise, so a filtered angle input is recommended; reported at the extremum frame.",
                    "kr": "구간 내 가장 큰 관절 각가속도로 부호를 유지합니다. 관절각을 두 번 미분해 구합니다. 클수록 각속도가 더 급격하게 변했다는 뜻입니다. 2차 미분은 잡음을 크게 증폭하므로 필터링된 각도 입력을 권장합니다. 극값 프레임에서 보고됩니다.",
                },
                "axes": {
                    "en": "Per joint-angle channel; sign follows the angle's ISB convention. Channel labels are abbreviated by plane: F/E (flex/ext), AB/ADD (ab/adduction), IR/ER (int/ext rotation); ankle uses Dorsi/Plantar and Inv/Ever. L/R = body side.",
                    "kr": "관절각 채널별; 부호는 각도의 ISB 규약을 따름. 채널 라벨은 평면별 약어로 표기: F/E(굴곡/신전), AB/ADD(외전/내전), IR/ER(내/외회전); 발목은 Dorsi/Plantar·Inv/Ever. L/R = 좌/우.",
                },
                "formula": "&alpha; = d<sup>2</sup>&theta;/dt<sup>2</sup> &nbsp;&rarr;&nbsp; peak = &theta;''<sub>|max|</sub>",
            },
        ],
    },
    {
        "cat": {"en": "Kinetics (force rate & impulse)", "kr": "운동역학 (힘 변화율 · 충격량)"},
        "metrics": [
            {
                "name": "Rate of force development (RFD)", "unit": "N/s",
                "desc": {
                    "en": "The steepest instantaneous slope of the force in the window (peak |dF/dt|, signed) — how explosively force is produced or released. Computed by differentiating the force once. The onset/window is whatever interval you select (or the per-cycle segment); RFD is the peak slope inside it. Filter the force first to avoid differentiating noise. Reported at the extremum frame.",
                    "kr": "구간 내 힘의 가장 가파른 순간 기울기(peak |dF/dt|, 부호 유지) — 힘을 얼마나 폭발적으로 내거나 빼는지를 나타냅니다. 힘을 한 번 미분해 구합니다. 시작점/구간은 선택한 구간(또는 cycle 분절)이며, RFD는 그 안의 최대 기울기입니다. 잡음 미분을 피하려면 힘을 먼저 필터링하세요. 극값 프레임에서 보고됩니다.",
                },
                "axes": {
                    "en": "Any force channel (typically vertical GRF); sign = force's own convention · onset = selected window",
                    "kr": "임의의 힘 채널(보통 수직 GRF); 부호 = 힘 자체 규약 · 시작 = 선택 구간",
                },
                "formula": "RFD = (dF/dt)<sub>|max|</sub>",
            },
            {
                "name": "Loading rate", "unit": "N/s",
                "desc": {
                    "en": "The average slope of the force across the window: (F at the last sample − F at the first) ÷ window duration. The window IS the loading interval (define it via the segment, e.g. initial contact → impact peak). Unlike RFD (a single steepest instant) this is the mean rate over the whole interval, so it is less sensitive to noise. Larger means force rises more quickly over the interval.",
                    "kr": "구간 전체에 걸친 힘의 평균 기울기: (구간 마지막 샘플의 힘 − 첫 샘플의 힘) ÷ 구간 길이. 구간 자체가 하중 구간입니다(segment로 정의, 예: 초기 접지 → 충격 피크). RFD(가장 가파른 한 순간)와 달리 구간 전체의 평균 변화율이라 잡음에 덜 민감합니다. 클수록 구간 동안 힘이 더 빨리 증가했다는 뜻입니다.",
                },
                "axes": {
                    "en": "Any force channel; T = (t at window end − t at window start)",
                    "kr": "임의의 힘 채널; T = (구간 끝 시각 − 구간 시작 시각)",
                },
                "formula": "LR = ( F[end] &minus; F[start] ) / T",
            },
            {
                "name": "Impulse", "unit": "N·s",
                "desc": {
                    "en": "Time integral of the force over the window — the area under the force–time curve (trapezoidal). Equals the change in momentum the force imparts. Computed over the selected window or per-cycle segment (e.g. heel-strike → toe-off for vertical-GRF impulse). All samples contribute regardless of sign, so the result carries the SIGN of the input channel. This app's Fz is already the upward-positive ground-reaction force (vGRF), so vertical-GRF impulse is positive during stance.",
                    "kr": "구간에 걸친 힘의 시간 적분 — 힘–시간 곡선 아래 면적(사다리꼴). 힘이 만든 운동량 변화와 같습니다. 선택 구간 또는 cycle 분절(예: 수직 GRF 충격량은 발뒤꿈치 접지 → 발가락 이지)에서 계산합니다. 부호와 무관하게 모든 샘플이 기여하므로, 결과는 입력 채널의 부호를 따릅니다. 이 앱의 Fz는 이미 위쪽 양수의 지면반력(vGRF)이므로, 수직 GRF 충격량은 입각기 동안 양수로 나옵니다.",
                },
                "axes": {
                    "en": "Any force channel; integrated over time t (seconds)",
                    "kr": "임의의 힘 채널; 시간 t(초)에 대해 적분",
                },
                "formula": "J = &int; F dt &nbsp; (trapezoidal)",
            },
            {
                "name": "Braking impulse", "unit": "N·s",
                "desc": {
                    "en": "Time integral of only the NEGATIVE (decelerating) part of the anterior–posterior GRF over the window — the impulse that slows the body during stance. Negative-sign samples are integrated; positive samples contribute nothing. Value is ≤ 0. Assumes anterior (forward) = positive; on a plate-local axis verify the force sign before naming it braking.",
                    "kr": "구간 동안 전후(AP) 지면반력 중 음수(감속) 부분만 시간 적분한 값 — 입각기에 신체를 감속시키는 충격량입니다. 음의 샘플만 적분되고 양의 샘플은 기여하지 않습니다. 값은 ≤ 0입니다. 전방(전진) = 양수를 가정하며, 발판 국소 축에서는 braking으로 부르기 전에 힘 부호를 확인하세요.",
                },
                "axes": {
                    "en": "AP (anterior–posterior) GRF, forward = + · only y < 0 samples integrated",
                    "kr": "AP(전후) 지면반력, 전진 = + · y < 0 샘플만 적분",
                },
                "formula": "J<sub>brake</sub> = &int; F<sub>AP</sub><sup>(&minus;)</sup> dt &nbsp; (F<sub>AP</sub> &lt; 0)",
            },
            {
                "name": "Propulsive impulse", "unit": "N·s",
                "desc": {
                    "en": "Time integral of only the POSITIVE (accelerating) part of the anterior–posterior GRF over the window — the impulse that drives the body forward during push-off. Positive-sign samples are integrated; negative samples contribute nothing. Value is ≥ 0. Assumes anterior (forward) = positive (same caveat as braking impulse).",
                    "kr": "구간 동안 전후(AP) 지면반력 중 양수(가속) 부분만 시간 적분한 값 — 추진(push-off) 시 신체를 전진시키는 충격량입니다. 양의 샘플만 적분되고 음의 샘플은 기여하지 않습니다. 값은 ≥ 0입니다. 전방(전진) = 양수를 가정합니다(braking impulse와 동일한 주의).",
                },
                "axes": {
                    "en": "AP (anterior–posterior) GRF, forward = + · only y > 0 samples integrated",
                    "kr": "AP(전후) 지면반력, 전진 = + · y > 0 샘플만 적분",
                },
                "formula": "J<sub>prop</sub> = &int; F<sub>AP</sub><sup>(+)</sup> dt &nbsp; (F<sub>AP</sub> &gt; 0)",
            },
        ],
    },
    {
        "cat": {"en": "Spatiotemporal (gait timing)", "kr": "시공간 (보행 타이밍)"},
        "metrics": [
            {
                "name": "Time between events", "unit": "s",
                "desc": {
                    "en": "The time elapsed between two gait events, computed per cycle and averaged over all cycles. This single op is the building block for every gait timing measure — what it MEANS is set by which two event labels you choose: stride time (heel-strike → next ipsilateral heel-strike), step time (contralateral → ipsilateral heel-strike), stance time (heel-strike → toe-off), swing time (toe-off → heel-strike), and for running contact time (heel-strike → toe-off) / flight time (toe-off → next heel-strike). Larger stride/step time means slower cadence.",
                    "kr": "두 보행 이벤트 사이의 경과 시간으로, cycle마다 계산해 전체 cycle에 대해 평균합니다. 이 하나의 연산이 모든 보행 타이밍 지표의 기본 블록입니다 — 어떤 두 이벤트 라벨을 고르느냐가 의미를 정합니다: stride time(발뒤꿈치 접지 → 같은 발 다음 접지), step time(반대발 → 같은발 접지), stance time(접지 → 이지), swing time(이지 → 접지), 러닝의 contact time(접지 → 이지) / flight time(이지 → 다음 접지). stride/step time이 클수록 케이던스가 느립니다.",
                },
                "axes": {
                    "en": "Per cycle, then mean ± SD over cycles · t = t(end event) − t(start event)",
                    "kr": "cycle별로 계산 후 cycle 전체 mean ± SD · t = t(끝 이벤트) − t(시작 이벤트)",
                },
                "formula": "&Delta;t = t<sub>end</sub> &minus; t<sub>start</sub>",
            },
            {
                "name": "Cadence", "unit": "steps/min",
                "desc": {
                    "en": "Step rate in steps per minute. From a STEP time (one foot contact to the next, opposite foot): 60 ÷ step time. From a STRIDE time (one full gait cycle = two steps): 120 ÷ stride time. Pick the convention that matches the time metric you reference. Higher cadence = faster stepping. A clinical staple of walking speed.",
                    "kr": "분당 걸음 수(steps/min). STEP time(한 발 접지에서 다음 반대발 접지까지) 기준: 60 ÷ step time. STRIDE time(완전한 한 보행주기 = 두 걸음) 기준: 120 ÷ stride time. 참조하는 시간 지표에 맞는 관례를 고르세요. 케이던스가 높을수록 빠른 스텝을 의미합니다. 보행 속도의 핵심 임상 지표입니다.",
                },
                "axes": {
                    "en": "Derived from a step/stride time metric (no axis)",
                    "kr": "step/stride time 지표에서 파생(축 무관)",
                },
                "formula": "cadence = 60 / t<sub>step</sub> &nbsp;=&nbsp; 120 / t<sub>stride</sub>",
            },
            {
                "name": "Stance %", "unit": "%",
                "desc": {
                    "en": "The fraction of the gait cycle spent in stance (foot on the ground), as a percent of stride time: stance time ÷ stride time × 100. Typical walking stance is ~60% (swing ~40%); a larger stance% suggests a slower, more cautious gait or a longer double-support. Computed by referencing a stance-time metric and a stride-time metric.",
                    "kr": "보행주기 중 입각기(발이 지면에 닿아 있는 시간)의 비율로, stride time 대비 백분율입니다: stance time ÷ stride time × 100. 보행 시 입각기는 보통 ~60%(유각기 ~40%)이며, stance%가 클수록 느리거나 조심스러운 보행, 또는 양발 지지기가 길다는 뜻일 수 있습니다. stance-time 지표와 stride-time 지표를 참조해 계산합니다.",
                },
                "axes": {
                    "en": "stance time and stride time both = a 'time between events' metric",
                    "kr": "stance time, stride time 모두 'time between events' 지표",
                },
                "formula": "stance% = t<sub>stance</sub> / t<sub>stride</sub> &times; 100",
            },
            {
                "name": "Swing %", "unit": "%",
                "desc": {
                    "en": "The fraction of the gait cycle spent in swing (foot off the ground), as a percent of stride time: swing time ÷ stride time × 100. Complement of stance% (stance% + swing% ≈ 100%). Computed by referencing a swing-time and a stride-time metric.",
                    "kr": "보행주기 중 유각기(발이 지면에서 떨어진 시간)의 비율로, stride time 대비 백분율입니다: swing time ÷ stride time × 100. stance%의 보수(stance% + swing% ≈ 100%)입니다. swing-time 지표와 stride-time 지표를 참조해 계산합니다.",
                },
                "axes": {
                    "en": "swing time and stride time both = a 'time between events' metric",
                    "kr": "swing time, stride time 모두 'time between events' 지표",
                },
                "formula": "swing% = t<sub>swing</sub> / t<sub>stride</sub> &times; 100",
            },
        ],
    },
    {
        "cat": {"en": "Spatial displacement (gait distance)", "kr": "공간 변위 (보행 거리)"},
        "metrics": [
            {
                "name": "Displacement between events", "unit": "(same as input signal)",
                "desc": {
                    "en": "Change in a signal between two events: signal[end event] − signal[start event], computed per cycle and averaged over all cycles. The building block for overground spatial gait measures — what it MEANS depends on the signal and event labels you choose: foot AP marker displacement between consecutive heel-strikes = stride length; between contralateral and ipsilateral heel-strike = step length; ML displacement between heel-strikes = step width. Works on any 1-D signal; the unit is preserved from the input.",
                    "kr": "두 이벤트 사이의 신호 변화: signal[끝 이벤트] − signal[시작 이벤트]로, cycle마다 계산해 전체 cycle 평균을 냅니다. 지면 보행의 공간 지표 기본 블록 — 어떤 신호·이벤트 라벨을 고르느냐가 의미를 정합니다: 발 AP 마커의 연속 heel-strike 간 변위 = stride length; 반대발·같은발 heel-strike 간 변위 = step length; heel-strike 간 ML 변위 = step width. 임의의 1차원 신호에 동작하며, 단위는 입력 신호의 단위를 그대로 유지합니다.",
                },
                "axes": {
                    "en": "Per cycle, then mean ± SD over cycles · AP = stride/step length; ML = step width",
                    "kr": "cycle별 계산 후 cycle 전체 mean ± SD · AP = stride/step length; ML = step width",
                },
                "formula": "&Delta;x = x[t<sub>end</sub>] &minus; x[t<sub>start</sub>]",
            },
        ],
    },
    {
        "cat": {"en": "Jump performance", "kr": "점프 수행력"},
        "metrics": [
            {
                "name": "Jump height (flight time)", "unit": "m",
                "desc": {
                    "en": "Jump height estimated from the time of flight: h = g·t²/8, where t is the airborne duration (takeoff event → landing event). Robust because it needs only two event times. Assumes takeoff and landing at the SAME height (valid for a counter-movement jump off the plate, not a drop jump landing lower). It over-estimates if the athlete tucks the legs in the air (which lengthens flight time).",
                    "kr": "체공 시간으로 추정한 점프 높이: h = g·t²/8, t는 체공 시간(이지 이벤트 → 착지 이벤트). 두 이벤트 시각만 필요해 견고합니다. 이지와 착지 높이가 같다고 가정합니다(발판 위 반동점프엔 유효, 더 낮게 착지하는 드롭점프엔 부적합). 공중에서 다리를 접으면(체공 시간이 길어져) 높이를 과대평가합니다.",
                },
                "axes": {
                    "en": "t = flight time (toe-off → landing); g = 9.80665 m/s²",
                    "kr": "t = 체공 시간(이지 → 착지); g = 9.80665 m/s²",
                },
                "formula": "h = g &middot; t<sup>2</sup> / 8",
            },
            {
                "name": "Jump height (impulse-momentum)", "unit": "m",
                "desc": {
                    "en": "Jump height from the net vertical impulse — the gold-standard force-plate method. Takeoff velocity v = J_net / m, where J_net = ∫(Fz − body weight) dt over the propulsion window and m is the subject mass; then h = v²/(2g). Unlike the flight-time method it does NOT assume equal takeoff/landing height, but it IS sensitive to the integration window and to an accurate body weight (best from a quiet-standing baseline). Needs subject mass (set in the run); missing mass → NaN.",
                    "kr": "순 수직 충격량으로 구한 점프 높이 — 포스플레이트 표준(gold-standard) 방법입니다. 이지 속도 v = J_net / m, J_net = 추진 구간에서 ∫(Fz − 체중)dt, m은 체질량; 그 다음 h = v²/(2g). 체공 시간 방법과 달리 이지/착지 높이가 같다고 가정하지 않지만, 적분 구간과 정확한 체중(정적 기립 baseline에서 구하는 것이 가장 좋음)에 민감합니다. 체질량이 필요하며(실행 시 설정), 없으면 NaN입니다.",
                },
                "axes": {
                    "en": "Fz = vertical GRF; window = propulsion phase (e.g. onset → takeoff); m = subject mass",
                    "kr": "Fz = 수직 지면반력; 구간 = 추진 구간(예: 시작 → 이지); m = 체질량",
                },
                "formula": "v = &int;(F<sub>z</sub> &minus; mg) dt / m &nbsp;&rarr;&nbsp; h = v<sup>2</sup> / (2g)",
            },
            {
                "name": "Takeoff velocity", "unit": "m/s",
                "desc": {
                    "en": "Vertical velocity of the body's centre of mass at takeoff, from the net impulse: v = ∫(Fz − body weight) dt ÷ mass over the propulsion window. The intermediate quantity behind the impulse-momentum jump height (h = v²/2g). Needs subject mass; missing mass → NaN.",
                    "kr": "이지 순간 신체 무게중심의 수직 속도로, 순 충격량에서 구합니다: v = 추진 구간에서 ∫(Fz − 체중)dt ÷ 체질량. 충격량-운동량 점프 높이(h = v²/2g)의 중간 값입니다. 체질량이 필요하며, 없으면 NaN입니다.",
                },
                "axes": {
                    "en": "Fz = vertical GRF; window = propulsion phase; m = subject mass",
                    "kr": "Fz = 수직 지면반력; 구간 = 추진 구간; m = 체질량",
                },
                "formula": "v = &int;(F<sub>z</sub> &minus; mg) dt / m",
            },
            {
                "name": "Reactive Strength Index (RSI)", "unit": "m/s",
                "desc": {
                    "en": "Reactive strength in a drop/rebound jump: jump height ÷ ground-contact time. Expresses how high the athlete rebounds per second of contact — higher RSI = more reactive/elastic (stiffer, faster stretch-shortening). Computed by referencing a jump-height metric and a contact-time metric (sometimes reported as mm/ms, equal to m/s).",
                    "kr": "드롭/반동 점프의 반응 근력: 점프 높이 ÷ 지면 접촉 시간. 접촉 1초당 얼마나 높이 튀어오르는지를 나타냅니다 — RSI가 클수록 더 반응적/탄성적(더 단단하고 빠른 신장-단축 주기). 점프 높이 지표와 접촉 시간 지표를 참조해 계산합니다(때때로 mm/ms로 보고하며 m/s와 같음).",
                },
                "axes": {
                    "en": "jump height (m) ÷ contact time (s); both referenced metrics",
                    "kr": "점프 높이(m) ÷ 접촉 시간(s); 둘 다 참조 지표",
                },
                "formula": "RSI = h<sub>jump</sub> / t<sub>contact</sub>",
            },
        ],
    },
    {
        "cat": {"en": "Symmetry & variability", "kr": "대칭 · 변동성"},
        "metrics": [
            {
                "name": "Symmetry index (Robinson SI)", "unit": "%",
                "desc": {
                    "en": "Robinson Symmetry Index: |L − R| ÷ (½(L + R)) × 100, where L and R are the SAME metric on the left and right limbs (e.g. stance time, peak vGRF). 0% = perfectly symmetric; larger = more asymmetric. The denominator is the two-limb mean, so the index is scale-independent. Sign is dropped (always ≥ 0) — use the symmetry ratio if direction matters.",
                    "kr": "Robinson 대칭 지수: |L − R| ÷ (½(L + R)) × 100, L과 R은 좌/우 다리의 같은 지표(예: stance time, peak vGRF)입니다. 0% = 완전 대칭, 클수록 비대칭이 큽니다. 분모가 양다리 평균이라 척도와 무관합니다. 부호는 버립니다(항상 ≥ 0) — 방향이 중요하면 대칭 비율을 쓰세요.",
                },
                "axes": {
                    "en": "L, R = the same metric on the left/right limb (two referenced metrics). L/R auto-assignment is Phase E; for now reference the two limb metrics explicitly.",
                    "kr": "L, R = 좌/우 다리의 같은 지표(참조 지표 2개). L/R 자동 배정은 Phase E이며, 지금은 두 다리 지표를 직접 참조해야 합니다.",
                },
                "formula": "SI = |L &minus; R| / (&frac12;(L + R)) &times; 100",
            },
            {
                "name": "Symmetry ratio (L/R)", "unit": "(ratio)",
                "desc": {
                    "en": "Simple left-to-right ratio of the same metric: L ÷ R. 1.0 = symmetric; >1 = left larger, <1 = right larger. Unlike the Robinson index it keeps direction (which side is greater). Computed by referencing the two limb metrics.",
                    "kr": "같은 지표의 단순 좌/우 비율: L ÷ R. 1.0 = 대칭, >1이면 왼쪽이 큼, <1이면 오른쪽이 큼. Robinson 지수와 달리 방향(어느 쪽이 큰지)을 유지합니다. 두 다리 지표를 참조해 계산합니다.",
                },
                "axes": {
                    "en": "L, R = the same metric on the left/right limb (two referenced metrics). L/R auto-assignment is Phase E.",
                    "kr": "L, R = 좌/우 다리의 같은 지표(참조 지표 2개). L/R 자동 배정은 Phase E.",
                },
                "formula": "ratio = L / R",
            },
            {
                "name": "Coefficient of variation (CV)", "unit": "%",
                "desc": {
                    "en": "Stride-to-stride variability of a per-cycle metric, normalised by its mean: SD ÷ |mean| × 100. SD is the sample SD (ddof = 1) over all cycles. Because it is scale-free, CV compares variability across metrics of different magnitude (e.g. stride time vs step length). Higher CV = less consistent gait (a clinical marker of fall risk / impaired motor control). Needs ≥ 2 cycles.",
                    "kr": "cycle별 지표의 stride-to-stride 변동성을 평균으로 정규화한 값: SD ÷ |평균| × 100. SD는 전체 cycle의 표본 표준편차(ddof = 1)입니다. 척도와 무관해 크기가 다른 지표들(예: stride time vs step length)의 변동성을 비교할 수 있습니다. CV가 클수록 보행 일관성이 낮습니다(낙상 위험 / 운동 조절 손상의 임상 지표). cycle이 2개 이상 필요합니다.",
                },
                "axes": {
                    "en": "Computed from the per-cycle array of one referenced metric",
                    "kr": "참조 지표 하나의 cycle별 배열에서 계산",
                },
                "formula": "CV = SD / |mean| &times; 100",
            },
        ],
    },
    {
        "cat": {"en": "Signal operations (building blocks)", "kr": "신호 연산 (기본 블록)"},
        "metrics": [
            {
                "name": "Derivative (rate of change)", "unit": "input unit ÷ s (e.g. deg → deg/s)",
                "desc": {
                    "en": "Differentiate a signal in time to get its rate of change: a Compute-signal step (the 'Derivative' calculation) that turns one curve into a new curve. Order 1 = velocity (position → speed, angle → angular velocity); Order 2 = acceleration (differentiate twice). It uses the ACTUAL time axis, so a non-uniform clock is handled correctly. The unit gains a '/s' per order (deg → deg/s → deg/s²). Differentiation amplifies noise, so filter the input first (a Filter step) — otherwise jitter dominates the result. Interior gaps (occluded samples) are interpolated across before differencing so one missing frame does not poison the whole derivative.",
                    "kr": "신호를 시간으로 미분해 변화율을 얻습니다: 곡선 하나를 새 곡선으로 바꾸는 Compute-signal 스텝('Derivative' 계산)입니다. Order 1 = 속도(위치 → 속력, 각도 → 각속도), Order 2 = 가속도(두 번 미분). 실제 시간 축을 사용하므로 비균일 클록도 올바르게 처리합니다. 단위는 차수마다 '/s'가 붙습니다(deg → deg/s → deg/s²). 미분은 잡음을 키우므로 입력을 먼저 필터링하세요(Filter 스텝) — 그렇지 않으면 떨림이 결과를 지배합니다. 중간 결측(occlusion)은 미분 전 보간으로 메워 한 프레임 결측이 전체 미분을 망치지 않게 합니다.",
                },
                "axes": {
                    "en": "Any 1-D signal; central difference in the interior, one-sided at the endpoints; t = actual sample times (s)",
                    "kr": "임의의 1차원 신호; 내부는 중앙차분, 양끝은 한쪽차분; t = 실제 표본 시각(s)",
                },
                "formula": "y&prime; = dy/dt &nbsp; (np.gradient) &nbsp;&nbsp; order 2: y&Prime; = d<sup>2</sup>y/dt<sup>2</sup>",
            },
            {
                "name": "Integral (accumulate over time)", "unit": "input unit × s (e.g. N → N·s)",
                "desc": {
                    "en": "Integrate a signal over time — the running area under the curve (trapezoidal). A Compute-signal step ('Integral' calculation) that produces a new curve (cumulative form, starting at 0) or, as a Metric, a single number (total area, e.g. impulse = ∫F dt). The unit gains '×s' (N → N·s, force → impulse). A 'sign gate' lets you integrate only the POSITIVE part (e.g. propulsive impulse), only the NEGATIVE part (braking impulse), or everything — useful for splitting a bipolar force into its forward/backward contributions. Interior gaps are interpolated before integrating.",
                    "kr": "신호를 시간으로 적분합니다 — 곡선 아래 누적 면적(사다리꼴). Compute-signal 스텝('Integral' 계산)으로 새 곡선(0에서 시작하는 누적 형태)을 만들거나, Metric으로 단일 값(전체 면적, 예: 충격량 = ∫F dt)을 냅니다. 단위에 '×s'가 붙습니다(N → N·s, 힘 → 충격량). '부호 게이트'로 양수 부분만(예: 추진 충격량), 음수 부분만(braking 충격량), 또는 전체를 적분할 수 있어 양극성 힘을 전진/후진 기여로 나눌 때 유용합니다. 중간 결측은 적분 전 보간합니다.",
                },
                "axes": {
                    "en": "Any 1-D signal; cumulative (curve, starts at 0) or total (scalar) · sign gate: all / pos (y>0) / neg (y<0)",
                    "kr": "임의의 1차원 신호; 누적(곡선, 0에서 시작) 또는 전체(스칼라) · 부호 게이트: all / pos(y>0) / neg(y<0)",
                },
                "formula": "Y(t) = &int;<sub>0</sub><sup>t</sup> y dt &nbsp; (trapezoidal) &nbsp;&nbsp; total = &int; y dt",
            },
            {
                "name": "Magnitude (resultant of axes)", "unit": "(same as the components)",
                "desc": {
                    "en": "Combine 2 or 3 component signals into their Euclidean resultant — the overall size regardless of direction. A Compute-signal step ('Magnitude' calculation) that takes a primary signal plus its extra axes. Use it for resultant ground-reaction force √(Fx²+Fy²+Fz²), marker speed from velocity components, or stride length from AP/ML displacement. The unit is unchanged (the components must share a unit). NaN-aware per sample: if any component is missing at a frame, that frame's resultant is NaN (a missing axis means the resultant is genuinely undefined there — it is NOT treated as zero).",
                    "kr": "구성 신호 2~3개를 유클리드 합성으로 결합합니다 — 방향과 무관한 전체 크기입니다. 기본 신호와 추가 축을 받는 Compute-signal 스텝('Magnitude' 계산)입니다. 합성 지면반력 √(Fx²+Fy²+Fz²), 속도 성분에서의 마커 속력, AP/ML 변위에서의 stride length 등에 씁니다. 단위는 그대로입니다(구성 신호는 같은 단위여야 함). 표본별 NaN 인식: 한 프레임에서 어느 성분이라도 결측이면 그 프레임 합성은 NaN입니다(빠진 축은 그 지점 합성이 정의되지 않음을 뜻하며, 0으로 취급하지 않습니다).",
                },
                "axes": {
                    "en": "2–3 component signals of the same unit (e.g. Fx, Fy, Fz) → one resultant of the same unit",
                    "kr": "같은 단위의 구성 신호 2~3개(예: Fx, Fy, Fz) → 같은 단위의 합성 1개",
                },
                "formula": "r = &radic;( x<sup>2</sup> + y<sup>2</sup> + z<sup>2</sup> )",
            },
            {
                "name": "Absolute value |x| (rectify)", "unit": "(same as input)",
                "desc": {
                    "en": "Take the absolute value of a signal — drop the sign so every sample is ≥ 0. A Compute-signal step ('Absolute value' calculation). Its main use is to RECTIFY a raw bipolar channel before measuring it: this app's raw C3D Fz can be down-negative, so |Fz| turns it into a positive vertical ground-reaction force you can take an impulse or peak of, WITHOUT any hidden global sign flip — you control the sign explicitly with this step. The unit is unchanged; NaN passes through untouched.",
                    "kr": "신호의 절대값을 취합니다 — 부호를 버려 모든 표본을 ≥ 0으로 만듭니다. Compute-signal 스텝('Absolute value' 계산)입니다. 주 용도는 측정 전에 양극성 원신호를 정류(RECTIFY)하는 것입니다: 이 앱의 원본 C3D Fz는 아래쪽-음수일 수 있어, |Fz|로 양의 수직 지면반력을 만들면 숨은 전역 부호 뒤집기 없이 충격량이나 피크를 잡을 수 있습니다 — 부호는 이 스텝으로 직접 제어합니다. 단위는 그대로이고, NaN은 그대로 통과합니다.",
                },
                "axes": {
                    "en": "Any 1-D signal; element-wise |x|, NaN preserved",
                    "kr": "임의의 1차원 신호; 원소별 |x|, NaN 보존",
                },
                "formula": "y = |x|",
            },
            {
                "name": "Normalize (÷ constant or ÷ metric)", "unit": "ratio (dimensionless, e.g. %BW)",
                "desc": {
                    "en": "Divide a signal by a value so it is expressed on a meaningful scale. A Compute-signal step ('Normalize' calculation): the divisor is either a CONSTANT you type (e.g. ÷ 1000 to convert mm → m) or a METRIC reference such as body weight (force ÷ body weight = %BW, force ÷ body mass = N/kg). Dividing by a subject value makes results comparable BETWEEN people of different size — the standard way to report force-plate data. The result is a ratio (the unit becomes dimensionless / %BW). The divisor is chosen inside this step's dialog, not in a global setting.",
                    "kr": "신호를 어떤 값으로 나눠 의미 있는 척도로 표현합니다. Compute-signal 스텝('Normalize' 계산): 나누는 값은 직접 입력하는 상수(예: mm → m 변환을 위한 ÷ 1000)이거나, 체중 같은 METRIC 참조입니다(힘 ÷ 체중 = %BW, 힘 ÷ 체질량 = N/kg). 피험자 값으로 나누면 체격이 다른 사람들 사이에서 결과를 비교할 수 있습니다 — 포스플레이트 데이터 보고의 표준 방식입니다. 결과는 비율이 됩니다(단위는 무차원 / %BW). 나누는 값은 전역 설정이 아니라 이 스텝의 다이얼로그 안에서 고릅니다.",
                },
                "axes": {
                    "en": "Any signal ÷ a constant OR a 'metric:<name>' reference (e.g. body weight, body mass)",
                    "kr": "임의의 신호 ÷ 상수 또는 'metric:<name>' 참조(예: 체중, 체질량)",
                },
                "formula": "y = x / b &nbsp;&nbsp; (b = constant or referenced metric)",
            },
            {
                "name": "Extrapolated CoM (XCOM, Hof 2005)", "unit": "(same as the COM position input, e.g. mm)",
                "desc": {
                    "en": "Extrapolated centre of mass — the dynamic-balance position of the COM (Hof, Gazendam & Sinke 2005). A Compute-signal step ('Extrapolated CoM' calculation) applied to ONE COM position axis (e.g. com:x): it adds the COM's velocity, scaled by the inverted-pendulum time constant, to its position, so the XCOM shows where the COM is 'heading'. A fast-moving COM extrapolates ahead of itself; a stationary COM gives XCOM = COM. It is the basis of the Margin-of-Stability framework. You supply the pendulum length L (the COM height, in METRES) in this step's dialog; with no length the result is NaN (we never guess L). The unit matches the COM position. ω₀ = √(g/L), g = 9.80665 m/s². NaN gaps in the COM are interpolated before differentiating.",
                    "kr": "외삽 무게중심(extrapolated CoM) — 무게중심의 동적 균형 위치입니다(Hof, Gazendam & Sinke 2005). 하나의 COM 위치 축(예: com:x)에 적용하는 Compute-signal 스텝('Extrapolated CoM' 계산)으로, COM 속도를 역진자 시간상수로 스케일해 위치에 더합니다. 그래서 XCOM은 COM이 '향하는' 위치를 보여줍니다. 빠르게 움직이는 COM은 자신보다 앞쪽으로 외삽되고, 정지한 COM은 XCOM = COM이 됩니다. 안정성 여유(Margin of Stability) 체계의 토대입니다. 진자 길이 L(COM 높이, 미터)을 이 스텝의 다이얼로그에서 입력하며, 길이가 없으면 결과는 NaN입니다(L을 추정하지 않음). 단위는 COM 위치와 같습니다. ω₀ = √(g/L), g = 9.80665 m/s². COM의 NaN 구간은 미분 전에 보간합니다.",
                },
                "axes": {
                    "en": "One COM position axis (world x/y/z, mm); L = pendulum length (COM height) in metres",
                    "kr": "하나의 COM 위치 축(world x/y/z, mm); L = 진자 길이(COM 높이), 미터 단위",
                },
                "formula": "XCOM = x + v / &omega;<sub>0</sub>,&nbsp; &omega;<sub>0</sub> = &radic;(g / L)",
            },
        ],
    },
    {
        "cat": {"en": "Binary metric operations", "kr": "이진 지표 연산"},
        "metrics": [
            {
                "name": "Product (a x b)", "unit": "(result unit = input1 × input2)",
                "desc": {
                    "en": "Multiply two metric values: a × b. Used to combine two metrics into a derived metric (e.g. gait speed = stride time × cadence per stride). The result unit is the product of the input units. NaN-safe: if either input is NaN or non-finite, the result is NaN.",
                    "kr": "두 지표 값의 곱: a × b. 두 지표를 합쳐 새로운 지표를 만듭니다(예: 보행 속도 = stride length × stride frequency). 결과 단위는 입력 단위의 곱입니다. NaN 안전: 입력 중 하나라도 NaN이거나 유한하지 않으면 결과도 NaN입니다.",
                },
                "axes": {
                    "en": "a, b = two referenced metric values (scalar inputs)",
                    "kr": "a, b = 참조된 두 지표 값(스칼라 입력)",
                },
                "formula": "result = a &times; b",
            },
            {
                "name": "Quotient (a / b)", "unit": "(result unit = input1 ÷ input2)",
                "desc": {
                    "en": "Divide two metric values: a ÷ b. Used to combine metrics into a derived ratio (e.g. overground gait speed = stride length ÷ stride time). The result unit is the ratio of the input units. NaN-safe: if either input is NaN, non-finite, or the divisor is zero, the result is NaN.",
                    "kr": "두 지표 값의 나눗셈: a ÷ b. 두 지표를 합쳐 새로운 비율 지표를 만듭니다(예: 지면 보행 속도 = stride length ÷ stride time). 결과 단위는 입력 단위의 비입니다. NaN 안전: 입력 중 하나라도 NaN이거나 유한하지 않거나, 분모가 0이면 결과는 NaN입니다.",
                },
                "axes": {
                    "en": "a, b = two referenced metric values (scalar inputs); b ≠ 0",
                    "kr": "a, b = 참조된 두 지표 값(스칼라 입력); b ≠ 0",
                },
                "formula": "result = a / b &nbsp;&nbsp; (b ≠ 0, else NaN)",
            },
            {
                "name": "Sum (a + b)", "unit": "(result unit = the shared input unit)",
                "desc": {
                    "en": "Add two metric values: a + b. Used to TOTAL two like-unit metrics into one (e.g. the two double-support intervals of a gait cycle, R_HS→L_TO and L_HS→R_TO, into the total double-support time). The result keeps the inputs' shared unit. NaN-safe: if either input is NaN or non-finite, the result is NaN.",
                    "kr": "두 지표 값의 합: a + b. 같은 단위의 두 지표를 하나로 합산할 때 사용합니다(예: 한 보행 주기의 두 이중지지 구간 R_HS→L_TO와 L_HS→R_TO를 더해 전체 이중지지 시간을 구함). 결과는 입력의 공통 단위를 유지합니다. NaN 안전: 입력 중 하나라도 NaN이거나 유한하지 않으면 결과도 NaN입니다.",
                },
                "axes": {
                    "en": "a, b = two referenced metric values (scalar inputs), same unit",
                    "kr": "a, b = 참조된 두 지표 값(스칼라 입력), 같은 단위",
                },
                "formula": "result = a + b",
            },
            {
                "name": "Double support %", "unit": "%",
                "desc": {
                    "en": "Total double-support time as a percent of the gait cycle: the time BOTH feet are on the ground (the sum of the two double-support intervals, R_HS→L_TO + L_HS→R_TO) divided by the stride (gait-cycle) time, ×100. Normal adult walking is ~20% (~10% per interval). It RISES with slower or less stable gait (a sensitive marker of balance impairment / fall risk) and falls toward 0% at running (no double support). Same math as Stance %/Swing % (phase ÷ stride ×100). NaN-safe; a non-positive stride → NaN.",
                    "kr": "전체 이중지지 시간을 보행 주기에 대한 백분율로 표현: 양발이 동시에 지면에 닿는 시간(두 이중지지 구간 R_HS→L_TO + L_HS→R_TO의 합)을 stride(보행 주기) 시간으로 나눈 뒤 ×100. 정상 성인 보행은 ~20%(구간당 ~10%)입니다. 보행이 느리거나 불안정할수록 증가하며(균형 저하·낙상 위험의 민감한 지표) 달리기에서는 0%로 떨어집니다(이중지지 없음). Stance %/Swing %와 같은 계산(구간 ÷ stride ×100)입니다. NaN 안전; stride가 0 이하이면 NaN.",
                },
                "axes": {
                    "en": "ds = total double-support time (s); stride = gait-cycle time (s)",
                    "kr": "ds = 전체 이중지지 시간(s); stride = 보행 주기 시간(s)",
                },
                "formula": "Double support % = ds / stride &times; 100",
            },
        ],
    },
    {
        "cat": {"en": "Frequency", "kr": "주파수"},
        "metrics": [
            {
                "name": "Mean power frequency", "unit": "Hz",
                "desc": {
                    "en": "Power-weighted average sway frequency from the COP power spectrum. Higher means more sway power at higher frequencies. The spectrum is the periodogram |FFT|² of the mean-subtracted COP with no windowing (DC removed); narrow-band sway off the FFT bin grid may show mild spectral leakage.",
                    "kr": "COP 파워 스펙트럼의 파워 가중 평균 주파수. 클수록 고주파 흔들림 성분이 많습니다. 스펙트럼은 평균을 뺀 COP의 주기도(periodogram, |FFT|²)이며 윈도잉 없이 계산합니다(DC 성분 제외). FFT 격자에 정확히 맞지 않는 좁은 대역 흔들림은 약간의 스펙트럼 누설(leakage)을 보일 수 있습니다.",
                },
                "axes": {"en": "Computed per axis (AP, ML)", "kr": "AP, ML 축별로 계산"},
                "formula": "f&#772; = &Sigma;( f &middot; P(f) ) / &Sigma; P(f)",
            },
            {
                "name": "Median frequency", "unit": "Hz",
                "desc": {
                    "en": "Frequency that splits the spectral power in half: 50% of the power lies below it and 50% above.",
                    "kr": "스펙트럼 파워를 절반으로 나누는 주파수 — 50%는 아래, 50%는 위에 있습니다.",
                },
                "axes": {"en": "Computed per axis (AP, ML)", "kr": "AP, ML 축별로 계산"},
                "formula": "&Sigma;<sub>f &le; f<sub>med</sub></sub> P  =  &frac12; &Sigma; P",
            },
        ],
    },
    {
        "cat": {"en": "Time-normalization & Ensemble", "kr": "시간정규화 · 앙상블"},
        "metrics": [
            {
                "name": "Time-normalization (0–100% cycle)", "unit": "% of cycle",
                "desc": {
                    "en": "Gait cycles never last the same number of frames (one stride may be 1.10 s, the next 1.14 s), so averaging them frame-by-frame would smear the curves. Time-normalization removes that duration difference: each cycle (an epoch) is resampled onto a fixed number of evenly spaced phase nodes — here the default is 101 nodes (0%, 1%, …, 100%). The resampling is plain linear interpolation between the epoch's original samples (numpy interp), with the FIRST sample mapped to 0% and the LAST to 100%; interior missing/occluded samples are interpolated across, while leading/trailing gaps stay blank (no extrapolation) and an epoch shorter than 2 samples is dropped. After this the % axis is a PHASE axis, not time: '70% of the cycle' marks the same biomechanical instant in every epoch, so curves of different durations become directly comparable and poolable. The cycle bounds come from detected events, so a wrong heel-strike/toe-off detection means a wrong epoch. References: Winter, Biomechanics and Motor Control of Human Movement [verify]; Sadeghi et al. 2000 [verify].",
                    "kr": "보행 주기는 매번 프레임 수가 다르므로(한 stride가 1.10초, 다음이 1.14초일 수 있음) 프레임 단위로 평균하면 곡선이 뭉개집니다. 시간정규화는 이 길이 차이를 제거합니다: 각 주기(epoch)를 고정된 개수의 등간격 위상 노드로 다시 표본화(resample)하며, 기본값은 101개(0%, 1%, …, 100%)입니다. 보간은 epoch의 원래 표본 사이를 잇는 단순 선형 보간(numpy interp)이고, 첫 표본이 0%·마지막 표본이 100%에 대응합니다. 중간 결측(occlusion)은 보간으로 메우고 앞/뒤 결측은 외삽 없이 빈 값으로 두며, 2표본 미만 epoch는 버립니다. 이후 % 축은 시간이 아니라 위상(phase) 축입니다: '주기의 70%'가 모든 epoch에서 같은 생체역학적 순간을 가리켜, 길이가 다른 곡선을 바로 비교·풀링할 수 있습니다. 주기 경계는 검출된 이벤트에서 오므로 잘못된 HS/TO 검출은 곧 잘못된 epoch입니다. 참고문헌: Winter, Biomechanics and Motor Control of Human Movement [verify]; Sadeghi et al. 2000 [verify].",
                },
                "axes": {
                    "en": "x-axis = % of the cycle (phase), default 101 nodes (0–100%); not seconds",
                    "kr": "x축 = 주기의 %(위상), 기본 101 노드(0–100%); 초가 아님",
                },
                "formula": "y(p) = interp( p, x<sub>orig</sub>, y<sub>orig</sub> ) &nbsp; p &isin; {0%, 1%, &hellip;, 100%}",
            },
            {
                "name": "Ensemble average (mean ± SD)", "unit": "(signal units)",
                "desc": {
                    "en": "Once every cycle is on the same 0–100% axis, the cycles are stacked into a matrix (rows = cycles/epochs, columns = the phase nodes) and each column is reduced to a mean and a standard deviation. The result is the ensemble curve: a mean trajectory with a ±SD band around it. The mean is the representative pattern; the SD band at each % of the cycle is the cycle-to-cycle variability at THAT instant — a narrow band means a highly repeatable movement, a wide band means that phase varies a lot (or that event timing is noisy there). The mean and SD are NaN-aware (an occluded node is dropped from that column's mean/SD via nanmean/nanstd, not allowed to poison it). SD is the sample SD (ddof = 1); with a single cycle the SD is 0.\n\nPER CYCLE vs PER SUBJECT (right-click the 'Ensemble overlay' row → Average). The question is what counts as one vote. 'Per cycle' (the default) pools every cycle with equal weight, so a subject who contributed 100 cycles pulls the group mean far more than one who contributed 20 — fine for a SINGLE subject (the band is then the genuine stride-to-stride variability), but biased for a group. 'Per subject' first averages each subject's cycles into ONE representative curve, then averages those curves across subjects, so every subject gets exactly one vote no matter how many cycles they walked; the SD band is then the BETWEEN-subject variability. Worked example at one phase node: subject A = 50° from 100 cycles, subject B = 60° from 20 cycles → per cycle = (100·50 + 20·60)/120 = 51.7° (dragged toward A); per subject = (50 + 60)/2 = 55° (A and B equal). The crucial property: per-subject needs NO equal cycle counts — unequal counts stop biasing the result. WHEN TO USE: choose PER SUBJECT for group/cohort comparisons ('what does this group's average gait look like') — the biomechanics standard for pooling across people; choose PER CYCLE for one subject's stride-to-stride variability, or when the individual cycles are themselves the unit of interest. (A single subject in per-subject mode gives n = 1 with no meaningful SD, which is why per cycle is the default.) To run statistics across the WHOLE curve (e.g. over which % of the cycle two groups differ), export the full per-cycle matrix and use SPM1D — one-dimensional Statistical Parametric Mapping, which tests every node while correcting for the correlation between neighbouring nodes. References: Pataky 2010, J Biomech 43(10):1976–1982; Pataky, Robinson & Vanrenterghem 2013, J Biomech 46(14):2394–2401 (SPM1D); Winter, Biomechanics and Motor Control of Human Movement [verify]; Sadeghi et al. 2000 [verify].",
                    "kr": "모든 주기가 같은 0–100% 축에 오면, 이들을 행렬로 쌓고(행 = 주기/epoch, 열 = 위상 노드) 각 열을 평균과 표준편차로 축약합니다. 결과가 앙상블 곡선입니다: 평균 궤적과 그 둘레의 ±SD 밴드. 평균은 대표 패턴이고, 각 주기 %에서의 SD 밴드는 그 순간의 주기 간 변동성입니다 — 밴드가 좁으면 재현성 높은 동작, 넓으면 그 구간이 많이 변동(또는 그 부근 이벤트 타이밍이 불안정)함을 뜻합니다. 평균·SD는 NaN 안전(결측 노드는 nanmean/nanstd로 해당 열에서 제외)입니다. SD는 표본 표준편차(ddof = 1)이고 주기가 하나면 0입니다.\n\nPER CYCLE vs PER SUBJECT ('Ensemble overlay' 행 우클릭 → Average). 핵심은 '무엇을 한 표로 보느냐'입니다. 'per cycle'(기본)은 모든 주기를 동등 가중으로 풀링하므로, 100주기를 낸 피험자가 20주기 낸 피험자보다 그룹 평균을 훨씬 더 끌어당깁니다 — 단일 피험자에는 적합(밴드가 진짜 걸음 간 변동성)하지만 그룹에는 편향됩니다. 'per subject'는 피험자별 주기를 먼저 하나의 대표 곡선으로 평균낸 뒤 그 곡선들을 피험자 간 평균하므로, 걸음 수와 무관하게 피험자마다 정확히 한 표를 갖습니다; 이때 SD 밴드는 피험자 간 변동성입니다. 한 위상 노드 예시: 피험자 A = 50°(100주기), B = 60°(20주기) → per cycle = (100·50 + 20·60)/120 = 51.7°(A 쪽으로 끌림); per subject = (50 + 60)/2 = 55°(A·B 동등). 결정적 성질: per subject는 걸음 수를 맞출 필요가 없습니다 — 개수 불균형이 결과를 편향시키지 않습니다. 언제 쓰나: 그룹/코호트 비교('이 집단의 평균 보행은?')에는 PER SUBJECT(사람 간 풀링의 생체역학 표준); 한 피험자의 걸음 간 변동성을 보거나 개별 주기 자체가 관심 단위일 때는 PER CYCLE. (단일 피험자를 per subject로 보면 n = 1이라 SD가 무의미 → 그래서 기본은 per cycle.) 곡선 전체에 대한 통계(예: 주기의 어느 % 구간에서 두 그룹이 다른가)는 주기별 전체 행렬을 내보내 SPM1D(1차원 Statistical Parametric Mapping)로 분석하며, 이는 이웃 노드 간 상관을 보정하면서 모든 노드를 검정합니다. 참고문헌: Pataky 2010, J Biomech 43(10):1976–1982; Pataky, Robinson & Vanrenterghem 2013, J Biomech 46(14):2394–2401 (SPM1D); Winter, Biomechanics and Motor Control of Human Movement [verify]; Sadeghi et al. 2000 [verify].",
                },
                "axes": {
                    "en": "mean ± SD per phase node; per-cycle (default) or per-subject weighted; NaN-aware; SD = sample SD (ddof = 1), 0 when n = 1",
                    "kr": "위상 노드별 mean ± SD; per-cycle(기본) 또는 per-subject 가중; NaN 안전; SD = 표본 표준편차(ddof = 1), n = 1이면 0",
                },
                "formula": "mean(p) = (1/N) &Sigma;<sub>i</sub> y<sub>i</sub>(p) &nbsp;&nbsp; SD(p) = &radic;( &Sigma;<sub>i</sub> (y<sub>i</sub>(p) &minus; mean(p))<sup>2</sup> / (N&minus;1) )",
            },
        ],
    },
    {
        "cat": {"en": "Gait events on a treadmill", "kr": "트레드밀 보행 이벤트"},
        "metrics": [
            {
                "name": "Treadmill gait-event detection (Zeni coordinate method)",
                "unit": "(events: heel-strike / toe-off)",
                "desc": {
                    "en": (
                        "How BalanceAnalyzer finds heel-strike (HS) and toe-off (TO) on a treadmill, "
                        "and why you can trust the timing. Read it in four parts.\n\n"

                        "LITERATURE. On a treadmill there is usually no clean per-foot ground-reaction edge "
                        "to threshold, so events are taken from foot MARKERS. Several marker methods are "
                        "validated against force-plate ground truth, and they agree on two things: HS is "
                        "detected more accurately than TO, and timing errors are small. Zeni, Richards & "
                        "Higginson (2008) introduced two kinematic methods — a 'coordinate' method (foot "
                        "marker position relative to the pelvis) and a 'velocity' method — both validated on "
                        "treadmill AND overground walking; the coordinate method is the common treadmill "
                        "standard. O'Connor et al. (2007) used the vertical velocity of a foot-marker "
                        "midpoint and reported HS error 16 ± 15 ms and TO error 9 ± 15 ms vs force plates. "
                        "Ghoussayni et al. (2004) thresholded foot tangential/linear velocity; Hreljac & "
                        "Marshall (2000) used vertical acceleration of heel/toe; Desailly et al. (2009) used "
                        "a high-pass-filtered trajectory method. Across this literature the consensus is "
                        "HS ~ <20 ms and TO larger (~20–50 ms): TO is the harder event for every kinematic "
                        "method.\n\n"

                        "METHOD. BalanceAnalyzer uses the Zeni (2008) COORDINATE method (core/gait_events.py). "
                        "Each foot marker's anterior–posterior (progression) coordinate is taken RELATIVE TO "
                        "THE PELVIS ORIGIN (the mean of the present ASIS/PSIS/sacrum markers) and oriented "
                        "anterior-positive (the toe is made to lead the heel along +AP). HS = a local MAXIMUM "
                        "of the heel AP-relative series (heel most anterior); TO = a local MINIMUM of the toe "
                        "AP-relative series (toe most posterior). The series are exposed as the "
                        "'gait:<SIDE>_<heel|toe>_ap' signals and the events are picked by the pipeline's peak "
                        "detector with a seconds-based refractory (min_distance_s) so one stride yields one "
                        "event. WHY THIS SUITS A TREADMILL: subtracting the pelvis origin removes the belt's "
                        "constant backward drift, so the foot's AP coordinate becomes a clean per-stride "
                        "oscillation whose turning points are HS and TO.\n\n"

                        "RESULTS (our two bundled treadmill trials — markers 100 Hz, master clock 1000 Hz). "
                        "Be honest about the setup: the force-plate channels in these files are flat ~0 N (the "
                        "floor plates sit at a different height/location than the belt, so the subject's load "
                        "never passed through them), so there is NO force ground truth and absolute accuracy "
                        "is unverifiable here; the markers are on the SHOE (~2–3 cm above the sole), and the "
                        "static trial was recorded OFF the treadmill, so vertical position is not a usable "
                        "contact reference. Validation here is therefore by INTERNAL CONSISTENCY (L/R "
                        "symmetry, cycle-to-cycle CV, one-event-per-stride count), not absolute error. "
                        "Zeni coordinate (our method): stance CEB 67.2% R / 67.2% L (CV 1.0%), KKM 68.7% R / "
                        "68.6% L (CV 1.4%); exactly one HS+TO per stride and L/R symmetric (CEB 178 strides, "
                        "KKM 228). O'Connor foot-centre vertical velocity over-detected (≈2× events on CEB, "
                        "CV 4–9%). Heel/toe vertical velocity was unreliable (CV 28–70%, strong L/R "
                        "asymmetry). Gait speed/stride length recovered from belt physics (during stance the "
                        "planted foot moves at belt = walking speed — a horizontal quantity unaffected by the "
                        "height issues): CEB ≈ 1.15 m/s (stride ≈ 1.28 m), KKM ≈ 0.89 m/s (stride ≈ 0.72 m); "
                        "with speed accounted for, the slower KKM correctly shows the higher stance%.\n\n"

                        "COMPARISON (the takeaway). On a treadmill the HORIZONTAL (AP) signal is belt-"
                        "confounded, but the pelvis-relative coordinate neutralises that; VERTICAL signals are "
                        "belt-independent in theory, but the foot's vertical velocity is multi-modal within a "
                        "stride, so naive vertical-velocity peak-picking over-detects. In practice the Zeni "
                        "coordinate method is the most consistent here and is the literature-validated "
                        "treadmill standard, so it is the recommended default. Honest caveat: a low CV means "
                        "PRECISION, not proven absolute accuracy (there is no force truth in these files), and "
                        "TO is the harder event for every kinematic method. Gait speed and stride length are "
                        "independently robust because they are horizontal quantities.\n\n"

                        "References: Zeni JA, Richards JG, Higginson JS (2008). Gait & Posture 27(4):710–714. "
                        "O'Connor CM, Thorpe SK, O'Malley MJ, Vaughan CL (2007). Gait & Posture 25(3):469–474. "
                        "Ghoussayni S, Stevens C, Durham S, Ewins D (2004). Gait & Posture 20(3):266–272. "
                        "Hreljac A, Marshall RN (2000). J Biomechanics 33(6):783–786. "
                        "Desailly E, Daniel Y, Sardain P, Lacouture P (2009). Gait & Posture 29(1):76–80."
                    ),
                    "kr": (
                        "BalanceAnalyzer가 트레드밀에서 발뒤꿈치 접지(HS)와 발가락 이지(TO)를 어떻게 찾고, 그 "
                        "타이밍을 왜 믿을 수 있는지 — 문헌 → 방법 → 결과 → 비교 네 부분으로 설명합니다.\n\n"

                        "문헌. 트레드밀에서는 보통 발별로 깨끗한 지면반력 가장자리를 임계값으로 잡을 수 없어, "
                        "이벤트를 발 마커에서 구합니다. 여러 마커 기반 방법이 포스플레이트 기준값에 대해 검증되었고, "
                        "두 가지에서 일치합니다: HS가 TO보다 더 정확하게 검출되며, 타이밍 오차는 작습니다. Zeni, "
                        "Richards & Higginson(2008)은 두 운동학 방법 — 'coordinate' 방법(골반 기준 발 마커 위치)과 "
                        "'velocity' 방법 — 을 제시했고, 둘 다 트레드밀과 오버그라운드 보행에서 검증되었습니다. "
                        "coordinate 방법이 트레드밀의 일반적 표준입니다. O'Connor 등(2007)은 발 마커 중점의 수직 "
                        "속도를 사용해 포스플레이트 대비 HS 오차 16 ± 15 ms, TO 오차 9 ± 15 ms를 보고했습니다. "
                        "Ghoussayni 등(2004)은 발의 접선/선속도 임계값을, Hreljac & Marshall(2000)은 heel/toe의 수직 "
                        "가속도를, Desailly 등(2009)은 고역통과(high-pass) 필터 궤적 방법을 사용했습니다. 이 문헌들의 "
                        "공통 결론은 HS ~ <20 ms, TO는 더 큼(~20–50 ms): TO가 모든 운동학 방법에서 더 어려운 "
                        "이벤트입니다.\n\n"

                        "방법. BalanceAnalyzer는 Zeni(2008) COORDINATE 방법을 사용합니다(core/gait_events.py). "
                        "각 발 마커의 전후(AP, 진행방향) 좌표를 골반 원점(존재하는 ASIS/PSIS/sacrum 마커들의 평균) "
                        "기준으로 취하고 전방-양수로 정렬합니다(toe가 +AP에서 heel보다 앞서도록). HS = heel AP-상대 "
                        "신호의 국소 최대값(heel이 가장 앞), TO = toe AP-상대 신호의 국소 최소값(toe가 가장 뒤). 이 "
                        "신호는 'gait:<SIDE>_<heel|toe>_ap'로 노출되며, 파이프라인의 peak 검출기가 초 단위 불응기"
                        "(min_distance_s)로 골라 한 stride당 한 이벤트가 나오게 합니다. 트레드밀에 적합한 이유: 골반 "
                        "원점을 빼면 벨트의 일정한 후방 드리프트가 제거되어, 발의 AP 좌표가 깨끗한 stride별 진동이 "
                        "되고 그 전환점이 HS·TO가 됩니다.\n\n"

                        "결과(번들 트레드밀 트라이얼 2개 — 마커 100 Hz, 마스터 클록 1000 Hz). 셋업을 정직하게 "
                        "밝힙니다: 이 파일들의 포스플레이트 채널은 평평한 ~0 N입니다(바닥 플레이트가 벨트와 다른 "
                        "높이/위치에 있어 피험자 하중이 통과하지 않음). 따라서 힘 기준값이 없어 절대 정확도는 여기서 "
                        "검증 불가이고, 마커는 신발(SHOE) 위(밑창에서 ~2–3 cm), 정적 트라이얼은 트레드밀 밖에서 "
                        "촬영되어 수직 위치를 접촉 기준으로 쓸 수 없습니다. 그래서 검증은 절대 오차가 아니라 내부 "
                        "일관성(L/R 대칭, cycle 간 CV, stride당 1이벤트 수)으로 합니다. Zeni coordinate(우리 방법): "
                        "stance CEB 67.2% R / 67.2% L (CV 1.0%), KKM 68.7% R / 68.6% L (CV 1.4%); stride당 정확히 "
                        "HS+TO 하나씩이고 L/R 대칭(CEB 178 strides, KKM 228). O'Connor 발-중점 수직 속도는 과검출"
                        "(CEB에서 약 2배, CV 4–9%). heel/toe 수직 속도는 불안정(CV 28–70%, 강한 L/R 비대칭). 벨트 "
                        "물리에서 복원한 보행속도/stride length(입각기 동안 디딘 발은 벨트 속도 = 보행 속도로 움직임 "
                        "— 높이 문제와 무관한 수평량): CEB ≈ 1.15 m/s (stride ≈ 1.28 m), KKM ≈ 0.89 m/s "
                        "(stride ≈ 0.72 m); 속도를 감안하면 더 느린 KKM이 올바르게 더 높은 stance%를 보입니다.\n\n"

                        "비교(요점). 트레드밀에서 수평(AP) 신호는 벨트에 오염되지만 골반-상대 좌표가 이를 "
                        "상쇄합니다. 수직 신호는 이론상 벨트와 무관하지만, 발의 수직 속도는 한 stride 안에서 "
                        "다봉(multi-modal)이라 단순 수직-속도 peak 잡기는 과검출합니다. 실제로 Zeni coordinate "
                        "방법이 여기서 가장 일관되며 문헌으로 검증된 트레드밀 표준이므로 권장 기본값입니다. 정직한 "
                        "주의: 낮은 CV는 정밀도(PRECISION)일 뿐 입증된 절대 정확도가 아니며(이 파일엔 힘 기준값 "
                        "없음), TO는 모든 운동학 방법에서 더 어려운 이벤트입니다. 보행속도·stride length는 수평량이라 "
                        "독립적으로 견고합니다.\n\n"

                        "참고문헌: Zeni JA, Richards JG, Higginson JS (2008). Gait & Posture 27(4):710–714. "
                        "O'Connor CM, Thorpe SK, O'Malley MJ, Vaughan CL (2007). Gait & Posture 25(3):469–474. "
                        "Ghoussayni S, Stevens C, Durham S, Ewins D (2004). Gait & Posture 20(3):266–272. "
                        "Hreljac A, Marshall RN (2000). J Biomechanics 33(6):783–786. "
                        "Desailly E, Daniel Y, Sardain P, Lacouture P (2009). Gait & Posture 29(1):76–80."
                    ),
                },
                "axes": {
                    "en": (
                        "AP = anterior–posterior (progression) axis, taken relative to the pelvis origin and "
                        "oriented anterior-positive. HS = max of 'gait:<SIDE>_heel_ap'; TO = min of "
                        "'gait:<SIDE>_toe_ap'. min_distance_s = refractory (one event per stride)."
                    ),
                    "kr": (
                        "AP = 전후(진행방향) 축, 골반 원점 기준·전방-양수. HS = 'gait:<SIDE>_heel_ap'의 최대, "
                        "TO = 'gait:<SIDE>_toe_ap'의 최소. min_distance_s = 불응기(stride당 1이벤트)."
                    ),
                },
                "formula": (
                    "AP<sub>rel</sub>(t) = sign &middot; ( foot<sub>AP</sub>(t) &minus; pelvis<sub>AP</sub>(t) ) "
                    "&nbsp;&rarr;&nbsp; HS = argmax<sub>local</sub> heel · AP<sub>rel</sub> &nbsp;&nbsp; "
                    "TO = argmin<sub>local</sub> toe · AP<sub>rel</sub>"
                ),
            },
        ],
    },
    {
        "cat": {"en": "Quick start — task presets", "kr": "빠른 시작 — 작업 프리셋"},
        "metrics": [
            {
                "name": "Walk preset (seeds a full pipeline)",
                "unit": "(builds a pipeline, not a number)",
                "desc": {
                    "en": (
                        "A preset gives a beginner a complete, working analysis in one click instead of a blank "
                        "pipeline. Open the '+' (Add step) popup: the FIRST group is 'Quick start', holding "
                        "'Walk (treadmill)' and 'Walk (overground)'. Picking one APPENDS a full ordered recipe of "
                        "steps that, together, take you from raw data to a gait report.\n\n"

                        "WHAT IT SEEDS (in order): (1) Filter — a 6 Hz low-pass on the markers so events, angles "
                        "and curves are smooth; (2) Compute joint angles — emits the hip/knee/ankle flexion "
                        "angles (angle:* signals) so they can be graphed; (3) Detect events — heel-strike (HS) "
                        "and toe-off (TO) for left and right (the treadmill preset uses the Zeni coordinate "
                        "method on foot markers; the overground preset uses the force-plate Fz threshold when a "
                        "loaded plate is present, otherwise it falls back to the same kinematic method); "
                        "(4) Spatiotemporal — stride/stance/swing time, stance %, swing %, cadence per side; "
                        "(5) Spatial — gait speed and stride length (treadmill: from belt-speed; overground: from "
                        "real foot displacement); (6) Kinematics — joint ROM, peak angular velocity, and "
                        "joint angle at heel-strike; (7) Normalize → Ensemble — each joint angle resampled to "
                        "0–100 % of the gait cycle so the Ensemble panel draws the mean ± SD curve; plus "
                        "double-support and left/right symmetry (and, overground, peak vGRF / impulse / loading "
                        "rate when force is present).\n\n"

                        "EVERY SEEDED STEP IS FULLY EDITABLE. The preset is just a non-blank starting point: after "
                        "adding it you can open any step and change its parameters (event thresholds, normalize "
                        "node count, which joints, etc.), reorder, delete, or add more steps. The pipeline is the "
                        "SOLE source of all derived data — angles, events, normalized curves and metrics exist "
                        "ONLY because a step in this recipe produces them, so the preset is also the easiest way "
                        "to SEE how a full analysis is wired together. References: Zeni et al. 2008 (HS/TO); "
                        "Winter, Biomechanics and Motor Control of Human Movement (gait parameters) [verify]."
                    ),
                    "kr": (
                        "프리셋은 빈 파이프라인 대신, 한 번의 클릭으로 초보자에게 완성된 분석을 제공합니다. '+'(Add "
                        "step) 팝업을 열면 첫 번째 그룹이 'Quick start'이고, 'Walk (treadmill)'과 'Walk "
                        "(overground)'이 들어 있습니다. 하나를 고르면 원본 데이터에서 보행 리포트까지 이어지는 완전한 "
                        "순서형 스텝 묶음이 파이프라인에 추가(APPEND)됩니다.\n\n"

                        "무엇을 깔아주나(순서대로): (1) Filter — 마커에 6 Hz 저역통과를 걸어 이벤트·각도·곡선을 "
                        "매끄럽게; (2) Compute joint angles — hip/knee/ankle 굴곡 각도(angle:* 신호)를 만들어 "
                        "그래프로 볼 수 있게; (3) Detect events — 좌/우 발뒤꿈치 접지(HS)·발가락 이지(TO)(트레드밀 "
                        "프리셋은 발 마커에 Zeni coordinate 방법을, 오버그라운드 프리셋은 하중이 실린 플레이트가 "
                        "있으면 포스플레이트 Fz 임계값을, 없으면 동일한 운동학 방법으로 대체); (4) Spatiotemporal — "
                        "측별 stride/stance/swing time, stance %, swing %, 케이던스; (5) Spatial — 보행 속도와 "
                        "stride length(트레드밀: 벨트 속도에서, 오버그라운드: 실제 발 변위에서); (6) Kinematics — "
                        "관절 ROM, 최대 각속도, 접지 시 관절각; (7) Normalize → Ensemble — 각 관절각을 보행주기 "
                        "0–100 %로 재표본화해 Ensemble 패널이 mean ± SD 곡선을 그리게; 그리고 양발 지지기와 "
                        "좌/우 대칭(오버그라운드는 힘이 있으면 peak vGRF / 충격량 / 로딩 레이트도).\n\n"

                        "깔린 모든 스텝은 완전히 편집 가능합니다. 프리셋은 빈 화면이 아닌 출발점일 뿐입니다: 추가 후 "
                        "어떤 스텝이든 열어 파라미터(이벤트 임계값, 정규화 노드 수, 대상 관절 등)를 바꾸고, 순서를 "
                        "바꾸거나, 삭제하거나, 스텝을 더 추가할 수 있습니다. 파이프라인은 모든 파생 데이터의 유일한 "
                        "출처입니다 — 각도·이벤트·정규화 곡선·지표는 이 레시피의 스텝이 만들기 때문에만 존재합니다. "
                        "그래서 프리셋은 완전한 분석이 어떻게 엮이는지 보기에도 가장 좋은 방법입니다. 참고문헌: "
                        "Zeni 등 2008(HS/TO); Winter, Biomechanics and Motor Control of Human Movement(보행 "
                        "파라미터) [verify]."
                    ),
                },
                "axes": {
                    "en": "Lives in the '+' Add-step popup, 'Quick start' group · appends an editable step recipe",
                    "kr": "'+' Add-step 팝업의 'Quick start' 그룹에 있음 · 편집 가능한 스텝 레시피를 추가",
                },
                "formula": (
                    "Filter &rarr; angles &rarr; HS/TO events &rarr; spatiotemporal · kinematics "
                    "&rarr; normalize &rarr; ensemble (mean &plusmn; SD)"
                ),
            },
        ],
    },
]

_TEXT = {
    "title": {"en": "COP Metrics Reference", "kr": "COP 지표 설명서"},
    "unit": {"en": "Unit", "kr": "단위"},
}

# Short hover descriptions for the sidebar metric checkboxes (per METRIC_KEYS).
METRIC_TOOLTIPS = {
    "RMS AP": "Typical AP sway amplitude (RMS around the mean).",
    "RMS ML": "Typical ML sway amplitude (RMS around the mean).",
    "Range AP": "Peak-to-peak AP excursion (max − min).",
    "Range ML": "Peak-to-peak ML excursion (max − min).",
    "Mean AP": "Average AP COP position (offset, not sway magnitude).",
    "Mean ML": "Average ML COP position (offset, not sway magnitude).",
    "Mean distance": "Mean radius of sway (mean COP distance from its centre).",
    "95% Ellipse area": "Area of the 95% COP confidence ellipse (sway dispersion).",
    "Sway path length": "Total distance the COP traveled along its path.",
    "Mean velocity": "Average COP speed (2-D path length ÷ duration).",
    "Mean velocity AP": "Average COP speed along the AP axis (1-D path ÷ duration).",
    "Mean velocity ML": "Average COP speed along the ML axis (1-D path ÷ duration).",
    "Sway area": "Area swept by the COP per unit time (AREA-SW).",
    "Mean power freq AP": "Power-weighted mean AP sway frequency.",
    "Mean power freq ML": "Power-weighted mean ML sway frequency.",
    "Median freq AP": "AP frequency splitting spectral power 50/50.",
    "Median freq ML": "ML frequency splitting spectral power 50/50.",
}

# Hover text for the named derivative/integral ops in the Metric Add-step popup
# (Round C UI). Keyed 1:1 with the Round B1 op keys in ``core.metrics`` (the
# named entries of ``OP_INFO``/``SCALAR_OPS``), not with COP METRIC_KEYS — these
# are pipeline ops, a different surface from the COP sidebar above. A regression
# test pins this 1:1 against the engine so it cannot drift.
OP_TOOLTIPS = {
    "peak_angular_velocity": "Fastest joint angular velocity in the window (d angle/dt). deg/s.",
    "peak_angular_acceleration": "Largest joint angular acceleration (d² angle/dt²). deg/s².",
    "rfd": "Steepest instantaneous force slope in the window (peak dF/dt). N/s.",
    "loading_rate": "Average force slope across the window (ΔF ÷ window time). N/s.",
    "impulse": "Area under the force–time curve (∫F dt) over the window. N·s.",
    "braking_impulse": "Impulse of the decelerating (negative AP) GRF. N·s, ≤ 0.",
    "propulsive_impulse": "Impulse of the accelerating (positive AP) GRF. N·s, ≥ 0.",
    # --- Round B2: spatiotemporal (event-pair) ops -------------------------
    "time_between_events": "Time between two events per cycle (stride/step/stance/swing/contact/flight). s.",
    "frames_between_events": "Frame count between two events per cycle. frames.",
    "jump_height_flight_time": "Jump height from flight time: g·t²/8. m.",
    # --- Round B2: impulse-momentum jump ops (need subject mass) -----------
    "jump_height_impulse": "Jump height from net vertical impulse: v²/2g (needs mass). m.",
    "takeoff_velocity": "Takeoff velocity from net impulse ÷ mass (needs mass). m/s.",
    # --- Round B2: symmetry / variability / derived ------------------------
    "cadence": "Cadence from step time: 60 / step time. steps/min.",
    "cadence_stride": "Cadence from stride time: 120 / stride time. steps/min.",
    "stance_pct": "Stance phase as % of stride (stance time ÷ stride time). %.",
    "swing_pct": "Swing phase as % of stride (swing time ÷ stride time). %.",
    "rsi": "Reactive Strength Index: jump height ÷ contact time. m/s.",
    "symmetry_index": "Robinson SI: |L−R| / (½(L+R)) × 100. 0% = symmetric. %.",
    "symmetry_ratio": "Symmetry ratio L/R (1.0 = symmetric). dimensionless.",
    "cv": "Stride-to-stride variability: SD ÷ mean × 100 (per-cycle). %.",
    "product": "Multiply two metric values: a × b. Result unit depends on inputs.",
    "quotient": "Divide two metric values: a ÷ b. Result unit depends on inputs.",
    "add": "Sum two like-unit metric values: a + b (e.g. total double-support time).",
    "double_support_pct": "Total double support as % of stride: ds ÷ stride × 100 (~20% normal). %.",
    # --- Spatial displacement (gait distance) ops --------------------------
    "displacement_between_events": (
        "Change in a signal between two events (signal at the end event minus the "
        "start event), per cycle. Used for spatial gait lengths (foot AP displacement "
        "= stride/step length; ML = step width)."
    ),
}


class _Collapsible(QWidget):
    """A disclosure-triangle section: click the header to show/hide its body."""

    def __init__(self, title, header_style, indent=0):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        self._title = title
        self.header = QPushButton("▸  " + title)
        self.header.setCheckable(True)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setStyleSheet(
            "QPushButton { background: transparent; border: none; text-align: left;"
            f"padding: 3px 2px; {header_style} }}"
            "QPushButton:hover { color: " + S.ACCENT_TEAL + "; }"
        )
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(indent, 2, 0, 4)
        self.body_layout.setSpacing(3)
        self.body.setVisible(False)
        self.header.toggled.connect(self._on_toggle)
        v.addWidget(self.header)
        v.addWidget(self.body)

    def _on_toggle(self, checked):
        self.body.setVisible(checked)
        self.header.setText(("▾  " if checked else "▸  ") + self._title)

    def add(self, widget):
        self.body_layout.addWidget(widget)


class MetricsHelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metrics Reference")
        self.setModal(False)
        self.resize(500, 600)
        self._lang = "en"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:16px;font-weight:700;")
        head.addWidget(self._title_lbl)
        head.addStretch()
        self._lang_btn = QPushButton()
        self._lang_btn.setObjectName("toggle-btn")
        self._lang_btn.setFixedHeight(22)
        self._lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lang_btn.clicked.connect(self._toggle_lang)
        head.addWidget(self._lang_btn)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;border:none;")
        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._col = QVBoxLayout(self._inner)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(2)
        scroll.setWidget(self._inner)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._populate()

    def _toggle_lang(self):
        self._lang = "kr" if self._lang == "en" else "en"
        self._populate()

    def _populate(self):
        lang = self._lang
        self._title_lbl.setText(_TEXT["title"][lang])
        self._lang_btn.setText("KOR" if lang == "en" else "EN")

        while self._col.count():
            item = self._col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cat_style = f"color:{S.TEXT_PRIMARY};font-size:13px;font-weight:700;"
        metric_style = f"color:{S.TEXT_SECONDARY};font-size:12px;font-weight:600;"
        for entry in METRIC_DOCS:
            cat = _Collapsible(entry["cat"][lang], cat_style, indent=10)
            for m in entry["metrics"]:
                metric = _Collapsible(m["name"], metric_style, indent=14)
                metric.add(self._content(m, lang))
                cat.add(metric)
            self._col.addWidget(cat)
        self._col.addStretch(1)

    def _content(self, m, lang):
        # Single outer border, no inner boxes (object-name scoped so the border
        # does not cascade onto the child labels).
        card = QFrame()
        card.setObjectName("help-card")
        card.setStyleSheet(
            f"QFrame#help-card {{ background:{S.BG_PANEL}; border:1px solid {S.BORDER};"
            " border-radius:6px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        unit_lbl = QLabel(f"{_TEXT['unit'][lang]}: {m['unit']}")
        unit_lbl.setStyleSheet(f"color:{S.ACCENT_TEAL};font-size:11px;font-weight:600;border:none;")
        lay.addWidget(unit_lbl)

        # One sentence per line for readability.
        desc = m["desc"][lang].replace(". ", ".\n")
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:12px;border:none;line-height:150%;")
        lay.addWidget(desc_lbl)

        axes = m["axes"][lang]
        if axes:
            axes_lbl = QLabel(axes)
            axes_lbl.setWordWrap(True)
            axes_lbl.setStyleSheet(f"color:{S.TEXT_SECONDARY};font-size:11px;border:none;")
            lay.addWidget(axes_lbl)

        formula_lbl = QLabel(m["formula"])
        formula_lbl.setTextFormat(Qt.TextFormat.RichText)
        formula_lbl.setWordWrap(True)
        formula_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        formula_lbl.setStyleSheet(
            f"color:{S.TEXT_PRIMARY};font-size:16px;font-style:italic;border:none;"
            "background:transparent;padding:4px 0 0 0;"
            "font-family:'Cambria Math','Cambria','Times New Roman',serif;"
        )
        lay.addWidget(formula_lbl)
        return card


# ---------------------------------------------------------------------------
# Markers & 3D guide
# ---------------------------------------------------------------------------
MARKER_DOCS = [
    {
        "title": {"en": "Loading marker data", "kr": "마커 데이터 불러오기"},
        "body": {
            "en": "C3D files can carry motion-capture marker (POINT) trajectories alongside force "
                  "data. Load one via File ▸ Load File. Marker rate (e.g. 100 Hz) may differ from the "
                  "force rate (e.g. 1000 Hz) — Balancelab keeps each on its own clock and syncs them "
                  "by time (seconds). Files with no markers simply show no marker panels; files with "
                  "markers but no force are supported too.",
            "kr": "C3D 파일은 힘 데이터와 함께 모션캡처 마커(POINT) 궤적을 담을 수 있습니다. File ▸ Load File로 "
                  "불러오세요. 마커 레이트(예: 100Hz)는 힘 레이트(예: 1000Hz)와 다를 수 있는데, Balancelab은 각자 "
                  "시계를 유지하고 시간(초)으로 동기화합니다. 마커가 없는 파일은 마커 패널이 안 뜨고, 마커만 있고 "
                  "힘이 없는 파일도 지원합니다.",
        },
    },
    {
        "title": {"en": "3D view & controls", "kr": "3D 뷰와 컨트롤"},
        "body": {
            "en": "Enable Graph ▸ 3D Markers to show the 3D scene. Left-drag rotates, the wheel zooms. "
                  "Right-click the 3D view for controls: Floor grid, Axes, Marker labels (off / on hover "
                  "/ always), Marker size, Reset view, and Position ▸ Left/Right to move the 3D pane. "
                  "Hovering a marker shows its name. The scene follows the playback slider — scrub or "
                  "press play and the markers animate in sync with the COP/force cursors.",
            "kr": "Graph ▸ 3D Markers를 켜면 3D 장면이 나타납니다. 좌클릭 드래그로 회전, 휠로 줌. 3D 뷰를 우클릭하면 "
                  "컨트롤이 나옵니다: 바닥 그리드, 축, 마커 이름표(끄기/호버/항상), 마커 크기, 뷰 리셋, 그리고 "
                  "Position ▸ Left/Right로 3D 패널 위치 이동. 마커에 커서를 올리면 이름이 보입니다. 장면은 재생 "
                  "슬라이더를 따라가며, 스크럽/재생 시 COP·force 커서와 동기화되어 움직입니다.",
        },
    },
    {
        "title": {"en": "Marker list", "kr": "마커 리스트"},
        "body": {
            "en": "The sidebar Markers section lists every marker. Use each row's checkbox to show or "
                  "hide that marker in 3D; click a row to highlight it in the 3D scene. The selected "
                  "marker is also the source for the coordinate plot.",
            "kr": "사이드바 Markers 섹션에 모든 마커가 나열됩니다. 각 행의 체크박스로 3D에서 해당 마커를 표시/숨기고, "
                  "행을 클릭하면 3D 장면에서 강조됩니다. 선택한 마커는 좌표 그래프의 대상이 됩니다.",
        },
    },
    {
        "title": {"en": "Marker coordinate plot", "kr": "마커 좌표 그래프"},
        "body": {
            "en": "Enable Graph ▸ Marker Coords to plot the selected marker's X/Y/Z position over time "
                  "next to the COP/force graphs. Toggle the X/Y/Z buttons in the Markers section to "
                  "choose which axes are drawn. The shared review cursor lines up across all plots.",
            "kr": "Graph ▸ Marker Coords를 켜면 선택한 마커의 X/Y/Z 위치를 시간에 따라 COP/force 그래프 옆에 표시합니다. "
                  "Markers 섹션의 X/Y/Z 버튼으로 그릴 축을 고르세요. 공유 리뷰 커서가 모든 그래프에서 정렬됩니다.",
        },
    },
]


# ---------------------------------------------------------------------------
# Rotation cross-talk & the CAST anatomical-frame fix
# ---------------------------------------------------------------------------
# A dedicated, bilingual explainer for why transverse-plane (internal/external
# rotation, IE) and frontal-plane (ab/adduction, AB) angles are the least
# reliable channels in surface-marker motion capture, how kinematic cross-talk
# inflates their ROM, and how the standard CAST anatomical-frame approach
# (Cappozzo 1995) fixes it. The numbers quoted (hip/knee/ankle ROM before &
# after) are from our own YA01/YA02 validation runs.
#
# Structure mirrors MARKER_DOCS (collapsible, en/kr ``body``) but each section
# also carries an optional ``points`` list (rendered as bullet lines) so the
# quantitative findings stay scannable. References live in CROSSTALK_REFS and
# are rendered as a trailing citation list under the last section.
CROSSTALK_DOCS = [
    {
        "title": {
            "en": "1. The problem — rotation cross-talk",
            "kr": "1. 문제 — 회전 cross-talk",
        },
        "body": {
            "en": "Transverse-plane rotation (internal/external rotation, IE) and "
                  "frontal-plane angles (ab/adduction, AB) are the LEAST reliable "
                  "joint angles in surface-marker motion capture. When the modelled "
                  "flexion axis is even slightly misaligned with the joint's true "
                  "rotation axis, pure flexion–extension (FE) 'leaks' into the IE and "
                  "AB channels. This is kinematic cross-talk, and its main visible "
                  "symptom is an IE/AB range of motion (ROM) that looks far larger "
                  "than it physiologically should be.",
            "kr": "횡단면 회전(internal/external rotation, IE)과 전두면 각도"
                  "(ab/adduction, AB)는 표면 마커 동작분석에서 가장 신뢰도가 낮은 "
                  "관절각입니다. 모델의 굴곡축(flexion axis)이 실제 관절 회전축과 "
                  "조금만 어긋나도, 순수 굴곡–신전(FE) 동작이 IE·AB 채널로 새어 "
                  "들어갑니다. 이것이 kinematic cross-talk이며, 가장 눈에 띄는 증상은 "
                  "IE·AB의 가동범위(ROM)가 생리적으로 가능한 것보다 훨씬 커 보이는 "
                  "것입니다.",
        },
        "points": {"en": [], "kr": []},
    },
    {
        "title": {
            "en": "2. Confirmed in our own data (YA01 / YA02)",
            "kr": "2. 우리 데이터로 정량 확인 (YA01 / YA02)",
        },
        "body": {
            "en": "We measured the symptom directly. With the old single-marker plane "
                  "method, hip IE ROM was as large as the hip flexion ROM — a classic "
                  "cross-talk signature — and knee FE↔IE were strongly correlated. The "
                  "mechanism: a few millimetres of soft-tissue wobble on the lateral "
                  "knee marker, acting on a very short lever arm, swung the segment's "
                  "medial–lateral (ML) axis by tens of degrees.",
            "kr": "이 증상을 직접 측정했습니다. 기존 단일 마커 plane 방식에서 hip IE ROM이 "
                  "hip 굴곡 ROM과 맞먹을 만큼 컸고(전형적 cross-talk 신호), 무릎 FE↔IE의 "
                  "상관도 높았습니다. 메커니즘: 외측 무릎 마커의 수 밀리미터 연부조직 "
                  "흔들림(wobble)이 매우 짧은 지렛대를 거치면서 분절의 좌우(ML)축을 "
                  "수십 도나 흔들었습니다.",
        },
        "points": {
            "en": [
                "Hip IE ROM (old method): 29° (YA01) / 39° (YA02) — as large as hip FE ROM (38–43°).",
                "Knee FE↔IE correlation: 0.85 (YA01) / 0.81 (YA02) — high coupling = cross-talk.",
                "Cause: 2.5–4 mm wobble of the lateral knee marker on a ~45 mm lever swung the segment ML axis by 28–40°.",
            ],
            "kr": [
                "Hip IE ROM (기존 방식): 29°(YA01) / 39°(YA02) — hip FE ROM(38–43°)과 맞먹음.",
                "무릎 FE↔IE 상관: 0.85(YA01) / 0.81(YA02) — 높은 결합 = cross-talk.",
                "원인: 외측 무릎 마커의 2.5–4 mm wobble이 ~45 mm 짧은 지렛대에서 분절 ML축을 28–40° 흔듦.",
            ],
        },
    },
    {
        "title": {
            "en": "3. The fix — CAST anatomical frames",
            "kr": "3. 해결 — CAST 분절좌표계",
        },
        "body": {
            "en": "The standard fix is the CAST technique (Cappozzo et al. 1995): define "
                  "each segment's anatomical axes ONCE from a static trial, then carry "
                  "those axes rigidly on a cluster of tracking markers throughout the "
                  "movement — instead of re-deriving an axis from a single live marker "
                  "every frame. Doing this normalises the inflated rotations while "
                  "leaving the trustworthy flexion channel essentially unchanged. This "
                  "is how standard software (e.g. Visual3D) works; the old code's habit "
                  "of using ONE live marker as a per-frame plane point was the "
                  "non-standard step that re-introduced cross-talk.",
            "kr": "표준 해결책은 CAST 기법(Cappozzo et al. 1995)입니다: 각 분절의 해부학적 "
                  "축을 정적(static) 트라이얼에서 한 번 정의한 뒤, 그 축을 추적 마커 "
                  "클러스터(tracking marker cluster)에 강체로 박아 동작 내내 이송합니다 — "
                  "매 프레임 단일 라이브 마커에서 축을 다시 만들지 않습니다. 이렇게 하면 "
                  "부풀려졌던 회전은 정상화되고, 신뢰할 수 있는 굴곡 채널은 거의 바뀌지 "
                  "않습니다. 이것이 Visual3D 등 표준 소프트웨어의 동작 방식이며, 기존 코드가 "
                  "'살아있는 단일 마커를 매 프레임 plane point로 쓰던' 방식이 cross-talk을 "
                  "다시 끌어들인 비표준 단계였습니다.",
        },
        "points": {
            "en": [
                "Hip IE ROM normalised: 29°/39° → 12° / 14° (physiological range).",
                "Flexion (FE) essentially unchanged: per-frame change RMS ≤ 1.7°.",
                "Knee varus/valgus corrected: 19° → 5.6°.",
                "Ankle inversion/eversion corrected: 21° → 9°.",
            ],
            "kr": [
                "Hip IE ROM 정상화: 29°/39° → 12° / 14° (생리적 범위).",
                "굴곡(FE)은 거의 불변: 프레임당 변화 RMS ≤ 1.7°.",
                "무릎 varus/valgus 교정: 19° → 5.6°.",
                "발목 inversion/eversion 교정: 21° → 9°.",
            ],
        },
    },
    {
        "title": {
            "en": "4. The foot's hard limit (an honest caveat)",
            "kr": "4. 발(FOOT)의 한계 (정직한 고지)",
        },
        "body": {
            "en": "This limit is specifically a TWO-MARKER (heel + toe) foot. Two points "
                  "define only a line (the foot's long axis), so there is no information to "
                  "recover foot inversion/eversion or rotation — nothing defines a "
                  "frontal/transverse foot axis. The frontal-plane markers we borrow "
                  "(lateral malleolus) sit on the LEG, not the foot, so foot inv/ev is "
                  "invisible to any analysis: a joint-model or statistical estimate would "
                  "only return its own assumptions, not a measurement. This limitation is "
                  "NOT permanent — it is lifted by adding paired medial+lateral markers ON "
                  "THE FOOT (a multi-segment foot model: Oxford Foot Model, Rizzoli), which "
                  "is a capture-protocol change, not an analysis trick. Every standard "
                  "package behaves the same way with a 2-marker foot: it trusts only ankle "
                  "dorsi/plantarflexion (FE) and treats inv/ev and rotation as low-"
                  "reliability. BalanceAnalyzer therefore tags ankle AB/IE channels as "
                  "'low reliability' until foot medial/lateral markers are present.",
            "kr": "이 한계는 정확히 '마커 2개(heel + toe)' 발일 때의 이야기입니다. 점 2개는 "
                  "직선(발의 장축)만 정의하므로, 발 내번/외번(inversion/eversion)·회전을 복원할 "
                  "정보가 없습니다 — 전두면/횡단면 축을 정의할 근거 자체가 없습니다. 빌려 쓰는 "
                  "전두면 마커(외측 복사뼈)는 발이 아니라 '다리'에 있어, 발 inv/ev는 어떤 분석으로도 "
                  "보이지 않습니다: 관절모델·통계추정을 써도 측정값이 아니라 '그 모델의 가정'이 "
                  "되돌아올 뿐입니다. 단, 이 한계는 영구적이지 않습니다 — '발 위'에 내·외측 마커쌍을 "
                  "추가(멀티세그먼트 발: Oxford Foot Model, Rizzoli)하면 풀립니다. 이는 분석 "
                  "트릭이 아니라 촬영 프로토콜의 변경입니다. 2-마커 발에서는 모든 표준 소프트웨어가 "
                  "동일하게 동작합니다: 발목 배측/저측굴곡(FE)만 신뢰하고 inv/ev·회전은 신뢰도 "
                  "낮음으로 처리합니다. 따라서 BalanceAnalyzer도 발에 내·외측 마커가 없는 한 발목 "
                  "AB/IE 채널을 'low reliability'로 표기합니다.",
        },
        "points": {
            "en": [
                "2 foot markers (heel + toe) → ankle inv/ev & rotation NOT measurable (artifact).",
                "+ medial & lateral markers ON THE FOOT → inv/ev becomes measurable (multi-segment foot).",
                "The fix is more markers (protocol), never a cleverer calculation.",
            ],
            "kr": [
                "발 마커 2개(heel + toe) → 발목 inv/ev·회전 측정 불가(인공산물).",
                "+ '발 위' 내·외측 마커 → inv/ev 측정 가능(멀티세그먼트 발).",
                "해결책은 마커 추가(프로토콜)이지, 더 똑똑한 계산이 아닙니다.",
            ],
        },
    },
    {
        "title": {
            "en": "5. How to read rotation angles",
            "kr": "5. 회전 각도 해석 권고",
        },
        "body": {
            "en": "Interpret rotation angles by left–right comparison, trends and "
                  "repeatability rather than by their absolute value. After the CAST "
                  "fix, hip rotation is reliable, but the knee's internal/external "
                  "rotation keeps a small residual flexion↔rotation coupling (its "
                  "physiological range is tiny and rides on a large flexion arc), so "
                  "BalanceAnalyzer tags knee IE as 'moderate reliability' — read its "
                  "trend, not its exact value. Where possible, attach paired medial/"
                  "lateral markers (which the CAST anatomical axis is built from).",
            "kr": "회전 각도는 절대값보다 좌우 비교, 경향(trend), 반복성(repeatability) 위주로 "
                  "해석하세요. CAST 보정 후 hip 회전은 신뢰할 수 있지만, 무릎의 "
                  "내·외회전(IE)은 약간의 굴곡↔회전 잔여 결합이 남습니다(생리적 회전 범위가 "
                  "매우 작고 큰 굴곡 호 위에 얹혀 있기 때문). 그래서 BalanceAnalyzer는 무릎 IE를 "
                  "'moderate(중간) 신뢰도'로 표기합니다 — 절대값보다 경향을 보세요. 가능하면 "
                  "내·외측 마커쌍(CAST 해부학적 축의 기준)을 부착하세요.",
        },
        "points": {"en": [], "kr": []},
    },
]

# Academic references for the cross-talk / CAST section. Each entry is a single
# citation string rendered as a hanging-indent line, optionally tagged with what
# it underpins (``tag``) and a URL (Visual3D docs). Page/volume numbers the user
# supplied are kept verbatim; for the two multi-segment-foot papers the user did
# NOT supply volume/pages, so those are deliberately left at journal+year and
# marked "verify" rather than fabricated.
CROSSTALK_REFS = [
    {
        "tag": {"en": "CAST", "kr": "CAST"},
        "cite": "Cappozzo A, Catani F, Della Croce U, Leardini A (1995). Position and "
                "orientation in space of bones during movement: anatomical frame "
                "definition and determination. Clinical Biomechanics 10(4):171–178.",
    },
    {
        "tag": {"en": "cross-talk sensitivity", "kr": "cross-talk 민감도"},
        "cite": "Piazza SJ, Cavanagh PR (2000). Measurement of the screw-home motion of "
                "the knee is sensitive to errors in axis alignment. Journal of "
                "Biomechanics 33(8):1029–1034.",
    },
    {
        "tag": {"en": "hip rotation profile", "kr": "hip 회전 프로파일"},
        "cite": "Baker R, Finney L, Orr J (1999). A new approach to determine the hip "
                "rotation profile from clinical gait analysis data. Human Movement "
                "Science 18:655–667.",
    },
    {
        "tag": {"en": "functional axes (SARA)", "kr": "기능적 축 (SARA)"},
        "cite": "Ehrig RM, Taylor WR, Duda GN, Heller MO (2007). A survey of formal "
                "methods for determining functional joint axes. Journal of "
                "Biomechanics 40(10):2150–2157.",
    },
    {
        "tag": {"en": "functional joints (AXIS)", "kr": "기능적 관절 (AXIS)"},
        "cite": "Schwartz MH, Rozumalski A (2005). A new method for estimating joint "
                "parameters from motion data. Journal of Biomechanics 38(1):107–116.",
    },
    {
        "tag": {"en": "cross-talk correction", "kr": "cross-talk 보정"},
        "cite": "Baudet A, Morisset C, d'Athis P, Maillefert J-F, Casillas J-M, "
                "Ornetti P, Laroche D (2014). Cross-talk correction method for knee "
                "kinematics in gait analysis using PCA. PLoS One 9(7):e102098.",
    },
    {
        "tag": {"en": "passive knee envelope", "kr": "수동 무릎 envelope"},
        "cite": "Blankevoort L, Huiskes R, de Lange A (1988). The envelope of passive "
                "knee joint motion. Journal of Biomechanics 21(9):705–720.",
    },
    {
        "tag": {"en": "lower-limb kinematics", "kr": "하지 운동학"},
        "cite": "Kadaba MP, Ramakrishnan HK, Wootten ME (1990). Measurement of lower "
                "extremity kinematics during level walking. Journal of Orthopaedic "
                "Research 8(3):383–392.",
    },
    {
        "tag": {"en": "multi-segment foot", "kr": "멀티세그먼트 발"},
        "cite": "Leardini A, Benedetti MG, Berti L, Bettinelli D, Nativo R, Giannini S "
                "(2007). Rear-foot, mid-foot and fore-foot motion during the stance phase "
                "of gait. Gait & Posture 25(3):453–462. · Stebbins J, Harrington M, "
                "Thompson N, Zavatsky A, Theologis T (2006). Repeatability of a model for "
                "measuring multi-segment foot kinematics in children (Oxford Foot Model). "
                "Gait & Posture 23(4):401–410.",
    },
]

# Visual3D documentation links underpinning the CAST / functional-joint approach.
CROSSTALK_LINKS = [
    {
        "label": {"en": "Visual3D — Functional Joints",
                  "kr": "Visual3D — Functional Joints"},
        "url": "https://wiki.has-motion.com/doku.php?id=visual3d:documentation:modeling:functional_joints:functional_joints",
    },
    {
        "label": {"en": "Visual3D — Segment Overview",
                  "kr": "Visual3D — Segment Overview"},
        "url": "https://has-motion.com/wiki/doku.php?id=visual3d:documentation:modeling:segments:segment_overview",
    },
    {
        "label": {"en": "Visual3D — Inverse Kinematics",
                  "kr": "Visual3D — Inverse Kinematics"},
        "url": "https://wiki.has-motion.com/doku.php?id=visual3d:documentation:kinematics_and_kinetics:inverse_kinematics",
    },
]


class MarkersHelpDialog(QDialog):
    """Collapsible, bilingual guide for the marker / 3D features."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Markers & 3D")
        self.setModal(False)
        self.resize(520, 560)
        self._lang = "en"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:16px;font-weight:700;")
        head.addWidget(self._title_lbl)
        head.addStretch()
        self._lang_btn = QPushButton()
        self._lang_btn.setObjectName("toggle-btn")
        self._lang_btn.setFixedHeight(22)
        self._lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lang_btn.clicked.connect(self._toggle_lang)
        head.addWidget(self._lang_btn)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;border:none;")
        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._col = QVBoxLayout(self._inner)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(2)
        scroll.setWidget(self._inner)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)
        self._populate()

    def _toggle_lang(self):
        self._lang = "kr" if self._lang == "en" else "en"
        self._populate()

    def _populate(self):
        lang = self._lang
        self._title_lbl.setText("Markers & 3D" if lang == "en" else "마커 & 3D")
        self._lang_btn.setText("KOR" if lang == "en" else "EN")
        while self._col.count():
            item = self._col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        style = f"color:{S.TEXT_PRIMARY};font-size:13px;font-weight:700;"
        for doc in MARKER_DOCS:
            sec = _Collapsible(doc["title"][lang], style, indent=10)
            body = QLabel(doc["body"][lang])
            body.setWordWrap(True)
            body.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:12px;border:none;line-height:150%;")
            sec.add(body)
            self._col.addWidget(sec)

        # --- Rotation cross-talk & CAST (its own grouped, foldable block) ---
        group_style = f"color:{S.TEXT_PRIMARY};font-size:14px;font-weight:700;"
        group_title = (
            "Rotation cross-talk & the CAST fix" if lang == "en"
            else "회전 cross-talk과 CAST 해결"
        )
        group = _Collapsible(group_title, group_style, indent=10)
        for doc in CROSSTALK_DOCS:
            sub = _Collapsible(doc["title"][lang], style, indent=14)
            sub.add(self._crosstalk_body(doc, lang))
            group.add(sub)
        # References + Visual3D links as the final foldable entry of the block.
        refs_title = "References" if lang == "en" else "참고문헌 (References)"
        refs = _Collapsible(refs_title, style, indent=14)
        refs.add(self._crosstalk_refs(lang))
        group.add(refs)
        self._col.addWidget(group)

        self._col.addStretch(1)

    def _crosstalk_body(self, doc, lang):
        """Body paragraph + optional bullet points for one cross-talk section."""
        card = QFrame()
        card.setObjectName("help-card")
        card.setStyleSheet(
            f"QFrame#help-card {{ background:{S.BG_PANEL}; border:1px solid {S.BORDER};"
            " border-radius:6px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        body = QLabel(doc["body"][lang])
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:12px;border:none;line-height:150%;")
        lay.addWidget(body)

        points = doc.get("points", {}).get(lang, [])
        for p in points:
            row = QLabel(f"•  {p}")
            row.setWordWrap(True)
            row.setStyleSheet(
                f"color:{S.TEXT_SECONDARY};font-size:11px;border:none;line-height:150%;"
                "padding-left:4px;"
            )
            lay.addWidget(row)
        return card

    def _crosstalk_refs(self, lang):
        """The academic reference list + Visual3D documentation links."""
        card = QFrame()
        card.setObjectName("help-card")
        card.setStyleSheet(
            f"QFrame#help-card {{ background:{S.BG_PANEL}; border:1px solid {S.BORDER};"
            " border-radius:6px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)

        for ref in CROSSTALK_REFS:
            tag = ref["tag"][lang]
            cite = ref["cite"]
            html = (
                f"<span style='color:{S.ACCENT_TEAL};font-weight:600;'>[{tag}]</span> "
                f"<span style='color:{S.TEXT_PRIMARY};'>{cite}</span>"
            )
            lbl = QLabel(html)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setStyleSheet("font-size:11px;border:none;line-height:150%;")
            lay.addWidget(lbl)

        links_hdr = QLabel("Visual3D documentation" if lang == "en" else "Visual3D 문서")
        links_hdr.setStyleSheet(
            f"color:{S.TEXT_SECONDARY};font-size:11px;font-weight:600;border:none;"
            "padding-top:4px;"
        )
        lay.addWidget(links_hdr)
        for link in CROSSTALK_LINKS:
            label = link["label"][lang]
            url = link["url"]
            lbl = QLabel(f"<a href='{url}' style='color:{S.ACCENT_PURPLE};'>{label}</a>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setOpenExternalLinks(True)
            lbl.setStyleSheet("font-size:11px;border:none;line-height:150%;")
            lay.addWidget(lbl)
        return card


# ---------------------------------------------------------------------------
# Time-normalization & Ensemble — pipeline concept guide
# ---------------------------------------------------------------------------
# A bilingual (en/kr) explainer for the time-normalize -> ensemble -> SPM-export
# pipeline. This describes the PIPELINE CONCEPTS (how epochs are resampled to a
# 0-100% axis, how the ensemble mean +- SD is built, and what the CSV export is
# for in an SPM workflow). It is deliberately kept out of METRIC_DOCS, which
# documents individual metric KEYS, not pipeline stages. Structure mirrors
# CROSSTALK_DOCS (en/kr ``body`` + optional ``points`` bullet list). References
# (TIMENORM_REFS) render as a trailing citation block; confirmed Pataky SPM
# citations are stated outright, the rest keep a [verify] tag rather than
# fabricating volume/page numbers.
TIMENORM_DOCS = [
    {
        "title": {
            "en": "1. Time normalization (0–100% of the cycle)",
            "kr": "1. 시간정규화 (주기의 0–100%)",
        },
        "body": {
            "en": "Movement cycles never last exactly the same number of frames — one "
                  "gait stride may be 1.10 s, the next 1.14 s. Comparing or averaging "
                  "them frame-by-frame would smear the curves. Time normalization "
                  "removes the duration difference: every cycle (an epoch) is resampled "
                  "onto a fixed number of evenly spaced phase nodes (default 101 = 0%, "
                  "1%, …, 100%). After this, '70% of the cycle' means the same "
                  "biomechanical instant in every epoch, so curves of different "
                  "durations become directly comparable and poolable. We use linear "
                  "interpolation between the epoch's original samples (numpy interp); "
                  "the first sample maps to 0% and the last to 100%. Interior missing "
                  "(occluded) samples are interpolated across; leading/trailing gaps "
                  "stay blank (no extrapolation). Caveats: linear interpolation "
                  "approximates between-sample behaviour as straight lines (negligible "
                  "with enough nodes); an epoch shorter than 2 samples is dropped (all "
                  "NaN); and the events that bound the cycles decide the quality — a "
                  "wrong heel-strike/toe-off detection means a wrong epoch.",
            "kr": "동작 주기는 매번 프레임 수가 다릅니다 — 한 보행 stride가 1.10초, 다음이 "
                  "1.14초일 수 있습니다. 이를 프레임 단위로 비교·평균하면 곡선이 뭉개집니다. "
                  "시간정규화는 이 길이 차이를 제거합니다: 각 주기(=epoch)를 고정된 개수의 "
                  "등간격 위상 노드(기본 101개 = 0%, 1%, …, 100%)로 다시 표본화(resample)"
                  "합니다. 이렇게 하면 '주기의 70%'가 모든 epoch에서 같은 생체역학적 순간을 "
                  "가리키므로, 길이가 다른 곡선들을 바로 비교하고 풀링(pooling)할 수 있습니다. "
                  "epoch의 원래 표본 사이를 선형 보간(numpy interp)하며, 첫 표본이 0%, "
                  "마지막 표본이 100%에 대응합니다. 중간 결측(occlusion)은 보간으로 메우고, "
                  "앞/뒤 결측은 외삽하지 않고 빈 값으로 둡니다. 한계: 선형 보간은 표본 사이를 "
                  "직선으로 근사합니다(노드가 충분하면 무시 가능); 2표본 미만인 epoch는 전부 "
                  "NaN으로 버려집니다; 그리고 주기 경계를 정하는 이벤트가 품질을 좌우합니다 — "
                  "잘못된 HS/TO 검출은 곧 잘못된 epoch입니다.",
        },
        "points": {
            "en": [
                "Cycle mode (gait): consecutive same-event pairs. Each cycle is event[k] → event[k+1] (e.g. R_HS → next R_HS = one full gait cycle). N heel strikes give N−1 cycles.",
                "Window mode (single discrete movement): start_event → the next end_event after it (e.g. movement onset → takeoff for a jump, or sit → stand). One epoch per start/end pair.",
                "Trial mode (whole recording): one epoch spanning frame 0 → last frame — the quiet-standing / whole-trial case with no repeating cycle.",
                "Nodes (points): default 101 gives 1% resolution (0–100% inclusive). More nodes = finer resolution but no new information beyond the raw sampling.",
                "Why it matters: without it you cannot average cycles or run group/curve statistics; with it the cycle becomes a unit you can mean, band, and compare across limbs/subjects.",
            ],
            "kr": [
                "Cycle 모드(보행): 같은 이벤트의 연속 쌍. 각 주기는 event[k] → event[k+1] (예: R_HS → 다음 R_HS = 한 보행 주기 전체). heel strike가 N개면 N−1 주기.",
                "Window 모드(단일 동작): start_event → 그 뒤 첫 end_event (예: 점프의 움직임 시작 → 이지(takeoff), 또는 앉기 → 일어서기). 시작/끝 쌍마다 1 epoch.",
                "Trial 모드(전체 trial): 0프레임 → 마지막 프레임의 단일 epoch — 반복 주기가 없는 정적/전체 trial용.",
                "노드 수(points): 기본 101은 1% 해상도(0–100% 포함). 노드를 늘리면 해상도는 올라가지만 원래 표본 이상의 새 정보는 없습니다.",
                "왜 필요한가: 정규화 없이는 주기 평균·곡선 통계가 불가능합니다. 정규화하면 주기가 '평균 내고, 밴드를 그리고, 좌우·피험자 간 비교'할 수 있는 단위가 됩니다.",
            ],
        },
    },
    {
        "title": {
            "en": "2. Ensemble average ± SD",
            "kr": "2. 앙상블 평균 ± 표준편차",
        },
        "body": {
            "en": "Once every cycle is on the same 0–100% axis, we stack them into a "
                  "matrix (rows = cycles/epochs, columns = the 101 phase nodes) and "
                  "reduce each column to a mean and a standard deviation. The result is "
                  "the ensemble curve: a mean trajectory with a ±SD band around it. The "
                  "mean is the subject's representative pattern; the SD band at each % of "
                  "the cycle is the cycle-to-cycle variability at that instant — a narrow "
                  "band means a highly repeatable movement, a wide band means the subject "
                  "varies that phase a lot (or that event detection is noisy there). The "
                  "mean and SD are epoch-weighted and NaN-aware: every pooled cycle "
                  "counts equally, and an occluded node in one cycle is simply dropped "
                  "from that column's mean/SD (nanmean/nanstd) rather than poisoning it. "
                  "SD is the sample SD (ddof = 1); with a single cycle the SD is 0. Read "
                  "the mean for the pattern, the SD band for consistency — a widening "
                  "band in mid-swing, for example, flags variable limb control or jittery "
                  "event timing.",
            "kr": "모든 주기가 같은 0–100% 축 위에 오면, 이들을 행렬로 쌓고(행 = 주기/epoch, "
                  "열 = 101개 위상 노드) 각 열을 평균과 표준편차로 축약합니다. 결과가 앙상블 "
                  "곡선입니다: 평균 궤적과 그 둘레의 ±SD 밴드. 평균은 피험자의 대표 패턴이고, "
                  "각 주기 %에서의 SD 밴드는 그 순간의 주기 간 변동성입니다 — 밴드가 좁으면 "
                  "매우 재현성 높은 동작, 넓으면 그 구간을 많이 변동시키거나(또는 그 부근 이벤트 "
                  "검출이 불안정함) 의미합니다. 평균·SD는 epoch 가중 + NaN 안전입니다: 풀링된 "
                  "모든 주기가 동등하게 반영되고, 한 주기에서 결측된 노드는 해당 열의 평균/SD"
                  "에서 그냥 제외됩니다(nanmean/nanstd). SD는 표본 표준편차(ddof = 1)이며, "
                  "주기가 하나면 SD는 0입니다. 평균은 패턴을, SD 밴드는 일관성을 읽습니다 — "
                  "예컨대 swing 중반에서 밴드가 넓어지면 사지 제어가 불안정하거나 이벤트 타이밍이 "
                  "흔들린다는 신호입니다.",
        },
        "points": {
            "en": [
                "Pooling unit = the trials you CHECK. The ensemble pools the epoch matrices of all checked trials into one matrix, then takes the mean/SD over that pool. One trial → within-trial (cycle-to-cycle); several trials of one subject → within-subject; trials of several subjects → a (currently epoch-weighted) cross-subject pool.",
                "Epoch-weighted, not trial-weighted: a trial with 200 cycles contributes 200 rows, a trial with 50 contributes 50. (A true group mean-of-subject-means would weight each subject equally; today's pool is epoch-level.)",
                "Column widths must match (same points count); pooling matrices of different node counts is rejected.",
            ],
            "kr": [
                "풀링 단위 = 체크한 트라이얼들. 앙상블은 체크된 모든 trial의 epoch 행렬을 하나로 합친 뒤 그 풀에 대해 평균/SD를 냅니다. 1 trial 체크 → trial 내(주기 간); 한 피험자의 여러 trial 체크 → 피험자 내; 여러 피험자의 trial 체크 → (현재는 epoch 가중) 피험자 간 풀.",
                "trial 가중이 아니라 epoch 가중: 200주기 trial은 200행, 50주기 trial은 50행을 기여합니다. (피험자별 평균을 다시 평균하는 진짜 group mean은 각 피험자를 동등 가중해야 함. 현재 풀은 epoch 수준입니다.)",
                "열 폭(points 수)이 같아야 합니다. 노드 수가 다른 행렬 풀링은 거부됩니다.",
            ],
        },
    },
    {
        "title": {
            "en": "3. Exporting for SPM (statistical parametric mapping)",
            "kr": "3. SPM(통계적 파라미터 매핑) 내보내기",
        },
        "body": {
            "en": "The 'mean ± SD' picture summarizes a curve into two numbers per node, "
                  "but statistics on a whole curve (e.g. 'over which % of the cycle do "
                  "two groups differ?') need the full set of curves, not just their mean. "
                  "That is what the CSV export gives: an N × 101 matrix (one row per "
                  "cycle/epoch, one column per 0–100% node), plus the mean and SD "
                  "columns. This is the native input format for SPM1D — one-dimensional "
                  "Statistical Parametric Mapping (Pataky). SPM1D runs a t-test / ANOVA "
                  "at every node while correcting for the correlation between neighbouring "
                  "nodes (random-field theory), so it tells you the specific phase "
                  "intervals where a difference is significant, instead of collapsing the "
                  "curve to a single scalar and testing that. Feeding it the per-cycle "
                  "matrix (not the mean) is essential — SPM needs the within-group spread "
                  "of the actual curves.",
            "kr": "'평균 ± SD' 그림은 곡선을 노드당 두 숫자로 요약하지만, 곡선 전체에 대한 "
                  "통계(예: '주기의 어느 % 구간에서 두 그룹이 다른가?')는 평균이 아니라 "
                  "곡선들의 전체 집합이 필요합니다. CSV 내보내기가 그것을 줍니다: N × 101 "
                  "행렬(주기/epoch당 1행, 0–100% 노드당 1열) + 평균·SD 열. 이는 SPM1D(1차원 "
                  "Statistical Parametric Mapping, Pataky)의 표준 입력 형식입니다. SPM1D는 "
                  "모든 노드에서 t-검정/ANOVA를 수행하되 이웃 노드 간 상관을 보정"
                  "(random-field theory)하므로, 곡선을 단일 스칼라로 뭉뚱그려 검정하는 대신 "
                  "차이가 유의한 구체적 위상 구간을 알려줍니다. 평균이 아니라 주기별 행렬을 넣는 "
                  "것이 핵심입니다 — SPM은 실제 곡선들의 그룹 내 분산을 필요로 합니다.",
        },
        "points": {
            "en": [
                "CSV layout: rows = phase nodes (0–100%), columns = each epoch + mean + sd (the transpose of the internal cycles × nodes matrix). SPM1D typically wants cycles × nodes; transpose on import if needed.",
                "One subject's many cycles → a within-subject SPM. Many subjects' mean curves → a between-subject SPM (build each subject's mean first).",
                "Correcting for inter-node correlation is what makes SPM valid where a naive 'paired t-test at every 1%' would massively inflate the false-positive rate.",
            ],
            "kr": [
                "CSV 배치: 행 = 위상 노드(0–100%), 열 = 각 epoch + mean + sd (내부의 cycles × nodes 행렬의 전치). SPM1D는 보통 cycles × nodes를 원하므로 필요 시 가져올 때 전치하세요.",
                "한 피험자의 여러 주기 → 피험자 내 SPM. 여러 피험자의 평균 곡선 → 피험자 간 SPM(먼저 각 피험자 평균을 만들 것).",
                "노드 간 상관 보정이 SPM을 타당하게 만듭니다. 순진하게 '1%마다 paired t-test'를 하면 거짓양성률이 폭증합니다.",
            ],
        },
    },
]

# References for the time-normalize / ensemble / SPM guide. The two confirmed
# Pataky SPM papers (volume:pages verified) are stated outright; the gait
# time-normalization / ensemble-average references that the author could not
# page-verify keep a "[verify ...]" note inside the citation rather than
# inventing exact volume/page numbers.
TIMENORM_REFS = [
    {
        "tag": {"en": "SPM (origin)", "kr": "SPM (원논문)"},
        "cite": "Pataky TC (2010). Generalized n-dimensional biomechanical field "
                "analysis using statistical parametric mapping. Journal of "
                "Biomechanics 43(10):1976–1982.",
    },
    {
        "tag": {"en": "SPM (vector field)", "kr": "SPM (벡터장)"},
        "cite": "Pataky TC, Robinson MA, Vanrenterghem J (2013). Vector field "
                "statistical analysis of kinematic and force trajectories. Journal of "
                "Biomechanics 46(14):2394–2401.",
    },
    {
        "tag": {"en": "SPM (0D vs 1D)", "kr": "SPM (0D vs 1D)"},
        "cite": "Pataky TC, Vanrenterghem J, Robinson MA (2015). Zero- vs. "
                "one-dimensional, parametric vs. non-parametric, and confidence "
                "interval vs. hypothesis testing procedures in one-dimensional "
                "biomechanical trajectory analysis. Journal of Biomechanics "
                "48(7):1277–1285. [verify volume/pages]",
    },
    {
        "tag": {"en": "ensemble average", "kr": "앙상블 평균"},
        "cite": "Winter DA (2009). Biomechanics and Motor Control of Human Movement, "
                "4th ed. Wiley. — the standard treatment of 0–100% gait normalization "
                "and the ensemble average ± 1 SD band. [verify exact chapter/pages]",
    },
    {
        "tag": {"en": "time-normalization", "kr": "시간정규화"},
        "cite": "Helwig NE, Hong S, Hsiao-Wecksler ET, Polk JD (2011). Methods to "
                "temporally align gait cycle data. Journal of Biomechanics "
                "44(3):561–565. [verify volume/pages]",
    },
    {
        "tag": {"en": "symmetry review", "kr": "대칭 리뷰"},
        "cite": "Sadeghi H, Allard P, Prince F, Labelle H (2000). Symmetry and limb "
                "dominance in able-bodied gait: a review. Gait & Posture "
                "12(1):34–45. [verify volume/pages]",
    },
]


class TimeNormHelpDialog(QDialog):
    """Collapsible, bilingual 'Time-normalization & Ensemble' pipeline guide.

    Mirrors MarkersHelpDialog (lang toggle, scroll area, _Collapsible folds,
    S colour tokens): three concept sections (time-normalize, ensemble ± SD,
    SPM export) each rendered as a body paragraph + bullet points, closing with
    the reference list. Describes pipeline CONCEPTS, not metric keys.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Time-normalization & Ensemble")
        self.setModal(False)
        self.resize(560, 600)
        self._lang = "en"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:16px;font-weight:700;")
        head.addWidget(self._title_lbl)
        head.addStretch()
        self._lang_btn = QPushButton()
        self._lang_btn.setObjectName("toggle-btn")
        self._lang_btn.setFixedHeight(22)
        self._lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lang_btn.clicked.connect(self._toggle_lang)
        head.addWidget(self._lang_btn)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;border:none;")
        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._col = QVBoxLayout(self._inner)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(2)
        scroll.setWidget(self._inner)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)
        self._populate()

    def _toggle_lang(self):
        self._lang = "kr" if self._lang == "en" else "en"
        self._populate()

    def _populate(self):
        lang = self._lang
        self._title_lbl.setText(
            "Time-normalization & Ensemble" if lang == "en"
            else "시간정규화 & 앙상블"
        )
        self._lang_btn.setText("KOR" if lang == "en" else "EN")
        while self._col.count():
            item = self._col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        style = f"color:{S.TEXT_PRIMARY};font-size:13px;font-weight:700;"
        for doc in TIMENORM_DOCS:
            sec = _Collapsible(doc["title"][lang], style, indent=12)
            sec.add(self._section_body(doc, lang))
            self._col.addWidget(sec)

        refs_title = "References" if lang == "en" else "참고문헌 (References)"
        refs = _Collapsible(refs_title, style, indent=12)
        refs.add(self._refs_card(lang))
        self._col.addWidget(refs)

        self._col.addStretch(1)

    def _section_body(self, doc, lang):
        """Body paragraph + optional bullet points for one concept section."""
        card = QFrame()
        card.setObjectName("help-card")
        card.setStyleSheet(
            f"QFrame#help-card {{ background:{S.BG_PANEL}; border:1px solid {S.BORDER};"
            " border-radius:6px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        body = QLabel(doc["body"][lang])
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:12px;border:none;line-height:150%;")
        lay.addWidget(body)

        for p in doc.get("points", {}).get(lang, []):
            row = QLabel(f"•  {p}")
            row.setWordWrap(True)
            row.setStyleSheet(
                f"color:{S.TEXT_SECONDARY};font-size:11px;border:none;line-height:150%;"
                "padding-left:4px;"
            )
            lay.addWidget(row)
        return card

    def _refs_card(self, lang):
        """The reference hanging-indent list (en/kr tags)."""
        card = QFrame()
        card.setObjectName("help-card")
        card.setStyleSheet(
            f"QFrame#help-card {{ background:{S.BG_PANEL}; border:1px solid {S.BORDER};"
            " border-radius:6px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)

        for ref in TIMENORM_REFS:
            tag = ref["tag"][lang]
            html = (
                f"<span style='color:{S.ACCENT_TEAL};font-weight:600;'>[{tag}]</span> "
                f"<span style='color:{S.TEXT_PRIMARY};'>{ref['cite']}</span>"
            )
            lbl = QLabel(html)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setStyleSheet("font-size:11px;border:none;line-height:150%;")
            lay.addWidget(lbl)
        return card


# ---------------------------------------------------------------------------
# Standard Marker Set — A Researcher's Reference
# ---------------------------------------------------------------------------
# A bilingual (en/kr) reference for HOW to build a standard, research-grade
# marker set so that each segment's three anatomical planes (sagittal/frontal/
# transverse) can be detected reliably. This is deliberately *separate* from the
# "Markers & 3D" cross-talk explainer: that one explains WHY rotation channels
# are unreliable and how CAST fixes them; THIS one is the marker-set recipe a
# researcher follows. They cross-reference each other rather than overlap.
#
# Each section carries an en/kr ``body`` and an optional en/kr ``points`` bullet
# list (mirrors CROSSTALK_DOCS). Two tables (TABLE A = per-segment marker set,
# TABLE B = realistic reliability ceiling) are rendered as RichText <table>s.
# References (14) + three Visual3D doc links close the dialog.

MARKERSET_DOCS = [
    {
        "title": {
            "en": "Part 0 — Scope & honest premise",
            "kr": "Part 0 — 범위와 정직한 전제",
        },
        "body": {
            "en": "'Measure every joint angle perfectly' is an unreachable goal: "
                  "soft-tissue artifact (STA) and kinematic cross-talk set a hard "
                  "ceiling that no marker set removes. The realistic goal is a "
                  "standard marker set DESIGNED so that each segment's three "
                  "anatomical planes — sagittal (flexion/extension), frontal "
                  "(ab/adduction), transverse (internal/external rotation) — can be "
                  "detected reliably. This page is not a new invention: it aligns "
                  "BalanceAnalyzer with an already-established standard (CAST and the "
                  "ISB conventions), so what you capture matches what professional "
                  "packages expect.",
            "kr": "'모든 관절각을 다 완벽히 측정한다'는 도달할 수 없는 목표입니다: 연부조직 "
                  "인공산물(STA)과 kinematic cross-talk가 어떤 마커셋으로도 못 없애는 천장을 "
                  "만듭니다. 현실적인 목표는, 각 분절의 세 해부학적 평면 — 시상면(굴곡/신전), "
                  "전두면(외전/내전), 횡단면(내·외회전) — 을 신뢰 가능하게 검출하도록 "
                  "'설계된' 표준 마커셋입니다. 이 페이지는 새로 만드는 것이 아니라, 이미 정립된 "
                  "표준(CAST와 ISB 규약)에 BalanceAnalyzer를 맞추는 것입니다. 그래야 촬영한 "
                  "데이터가 전문 소프트웨어가 기대하는 형태와 일치합니다.",
        },
        "points": {"en": [], "kr": []},
    },
    {
        "title": {
            "en": "Part 1 — The one principle (CAST)",
            "kr": "Part 1 — 단 하나의 원리 (CAST)",
        },
        "body": {
            "en": "Everything below reduces to one principle (Cappozzo et al. 1995, "
                  "CAST): (1) track EVERY segment as a rigid cluster of at least three "
                  "non-collinear markers (four recommended); (2) define each rotation "
                  "axis from a PAIR of markers (medial + lateral) or a functional "
                  "method — never from a single marker; and (3) keep the axis-defining "
                  "markers (used only in the static trial) SEPARATE from the tracking "
                  "markers (the dynamic cluster). A single plane marker is the chief "
                  "culprit: a few millimetres of STA on a short lever swings the "
                  "segment's medial–lateral axis by tens of degrees, which is the root "
                  "of rotation cross-talk. In our own YA01/YA02 data the old "
                  "single-marker method inflated hip IE ROM to 29°/39°; the CAST "
                  "approach brought it back to 12°/14°. (See Markers & 3D ▸ Rotation "
                  "cross-talk & the CAST fix for the full numbers.)",
            "kr": "아래 모든 내용은 하나의 원리로 요약됩니다(Cappozzo et al. 1995, CAST): "
                  "(1) 모든 분절을 비공선 마커 3개 이상(권장 4개)의 강체 클러스터로 추적, "
                  "(2) 각 회전축을 단일 마커가 아니라 '양측(내·외측) 마커쌍' 또는 functional "
                  "방법으로 정의, (3) 축 정의 마커(static 트라이얼에서만 사용)와 추적 마커"
                  "(동적 클러스터)를 '분리'. 단일 plane 마커가 주범입니다: 짧은 지렛대 위 수 "
                  "밀리미터의 STA가 분절의 좌우(ML)축을 수십 도 흔들고, 이것이 회전 cross-talk의 "
                  "근원입니다. 우리 YA01/YA02 데이터에서 기존 단일 마커 방식은 hip IE ROM을 "
                  "29°/39°로 부풀렸고, CAST 방식이 이를 12°/14°로 되돌렸습니다. (전체 수치는 "
                  "Markers & 3D ▸ 회전 cross-talk과 CAST 해결 참조.)",
        },
        "points": {
            "en": [
                "(1) Rigid cluster: ≥3 non-collinear markers per segment (4 recommended).",
                "(2) Axis from a PAIR (medial + lateral) or functional — never one marker.",
                "(3) Separate axis-defining (static-only) markers from tracking (cluster) markers.",
            ],
            "kr": [
                "(1) 강체 클러스터: 분절당 비공선 마커 3개 이상(권장 4개).",
                "(2) 축은 '양측 쌍(내·외측)' 또는 functional로 — 절대 단일 마커로 정의하지 않음.",
                "(3) 축 정의(static 전용) 마커와 추적(클러스터) 마커를 분리.",
            ],
        },
    },
    {
        "title": {
            "en": "Part 2 — Standard marker set per segment (Table A)",
            "kr": "Part 2 — 분절별 표준 마커셋 (핵심 Table A)",
        },
        "body": {
            "en": "The table below is the core recipe: for each segment it lists the "
                  "axis-defining markers (placed for the static trial, then removed), "
                  "the tracking cluster carried through the movement, how the joint "
                  "centre / axis is obtained, and the resulting three-plane "
                  "reliability. Bold items are the rotation-axis essentials — the "
                  "paired (medial/lateral) markers without which a plane collapses. "
                  "The axis-defining markers are captured once in the static pose, "
                  "then cluster-embedded (expressed in the cluster's local frame) so "
                  "they can be removed and still carried rigidly through the dynamic "
                  "trial.",
            "kr": "아래 표가 핵심 레시피입니다: 각 분절에 대해 축 정의 마커(static 촬영용, 이후 "
                  "제거), 동작 내내 이송하는 추적 클러스터, 관절중심/축을 얻는 방법, 그리고 "
                  "결과적인 3평면 신뢰도를 정리합니다. 굵은 항목은 회전축의 핵심 — 없으면 평면이 "
                  "무너지는 양측(내·외측) 마커쌍 — 입니다. 축 정의 마커는 static 자세에서 한 번 "
                  "촬영한 뒤 클러스터 로컬 좌표계에 박아(cluster-embed) 두므로, 마커를 떼어도 "
                  "동적 트라이얼 내내 강체로 이송됩니다.",
        },
        "table": "A",
        "caption": {
            "en": "Bold = the rotation-axis essentials (paired markers). Axis-defining "
                  "markers are captured in the static trial and then removed, carried "
                  "rigidly by cluster-embedding.",
            "kr": "굵은 항목 = 회전축을 살리는 핵심(양측 쌍). axis-defining 마커는 static 촬영 후 "
                  "제거하고, 클러스터로 강체 이송(cluster-embed)합니다.",
        },
    },
    {
        "title": {
            "en": "Part 3 — Axis-defining vs tracking markers (the heart of CAST)",
            "kr": "Part 3 — 축 정의 마커 vs 추적 마커 (CAST의 요체)",
        },
        "body": {
            "en": "Why split the two roles? The anatomical axis is defined ONCE in the "
                  "static trial from a paired (medial/lateral) landmark or palpation, "
                  "then embedded in the tracking cluster's local frame; during the "
                  "dynamic trial the axis is reconstructed from the cluster's rigid "
                  "pose, not re-derived from a single live marker every frame. The "
                  "cluster averages out single-marker palpation error and STA, which a "
                  "lone live marker would feed straight into the rotation channels. "
                  "This is exactly how BalanceAnalyzer's thigh/shank handling works, "
                  "and it is the step that normalised the inflated hip/knee rotations.",
            "kr": "왜 두 역할을 나눌까요? 해부학적 축은 static 트라이얼에서 양측(내·외측) 표식 또는 "
                  "촉진으로 '한 번' 정의한 뒤 추적 클러스터의 로컬 좌표계에 박아 둡니다; 동적 "
                  "트라이얼에서는 매 프레임 단일 라이브 마커로 다시 만들지 않고, 클러스터의 강체 "
                  "pose로부터 축을 재구성합니다. 클러스터가 단일 마커의 촉진 오차와 STA를 평균으로 "
                  "걸러내는데, 단일 라이브 마커는 그 오차를 회전 채널로 곧장 흘려보냅니다. 이것이 "
                  "BalanceAnalyzer의 thigh/shank 처리 방식이며, 부풀려진 hip/knee 회전을 "
                  "정상화한 바로 그 단계입니다.",
        },
        "points": {"en": [], "kr": []},
    },
    {
        "title": {
            "en": "Part 4 — Functional calibration (SARA / SCoRE)",
            "kr": "Part 4 — 기능적 보정 (SARA / SCoRE)",
        },
        "body": {
            "en": "The best rotation axes and joint centres come from FUNCTIONAL "
                  "calibration: SARA estimates a hinge axis (knee, elbow) and SCoRE "
                  "estimates a ball-joint centre (hip, shoulder) from the relative "
                  "motion of two clusters, removing even the paired-marker palpation "
                  "error. The catch is that they need a calibration motion with enough "
                  "range of motion — open-chain knee flexion/extension for SARA, a hip "
                  "'hula'/circumduction for SCoRE. For tasks with little ROM (quiet "
                  "balance, standing) there is not enough motion to fit the axis "
                  "reliably, so fall back to the paired-marker static definition, "
                  "which is safe and ROM-independent.",
            "kr": "최선의 회전축과 관절중심은 functional 보정에서 나옵니다: SARA는 경첩축"
                  "(무릎·팔꿈치)을, SCoRE는 볼관절 중심(고관절·어깨)을 두 클러스터의 상대 "
                  "운동으로 추정해, 양측 마커의 촉진 오차까지 제거합니다. 단, 충분한 가동범위"
                  "(ROM)를 가진 보정 동작이 필요합니다 — SARA는 개방연쇄 무릎 굴신, SCoRE는 "
                  "고관절 'hula'(휘돌리기). ROM이 작은 과제(정적 균형, 기립)에서는 축을 안정적으로 "
                  "맞출 만큼 움직임이 없으므로, 안전하고 ROM에 무관한 '양측-쌍 정적 정의'로 "
                  "폴백하세요.",
        },
        "points": {
            "en": [
                "SARA = functional ROTATION AXIS (hinge joints: knee, elbow).",
                "SCoRE = functional JOINT CENTRE (ball joints: hip, shoulder).",
                "Needs a high-ROM calibration trial; low-ROM tasks → paired-marker static fallback.",
            ],
            "kr": [
                "SARA = 기능적 회전축(경첩 관절: 무릎·팔꿈치).",
                "SCoRE = 기능적 관절중심(볼 관절: 고관절·어깨).",
                "고-ROM 보정 trial 필요; 저-ROM 과제 → 양측-쌍 정적 정의로 폴백.",
            ],
        },
    },
    {
        "title": {
            "en": "Part 5 — Cluster placement (minimising STA)",
            "kr": "Part 5 — 클러스터 부착 위치 (STA 최소화)",
        },
        "body": {
            "en": "Where the tracking cluster sits decides how much STA it carries. "
                  "Avoid muscle bellies (where they bulge under contraction) and the "
                  "ends of the segment near the joint line (where skin slides most). "
                  "Place the thigh cluster distally and laterally; place the shank "
                  "cluster on the antero-lateral tibial surface, where bone is close "
                  "under the skin. A rigid marker plate (cluster on a stiff shell) "
                  "moves as one body and beats four loose skin markers for keeping the "
                  "cluster rigid.",
            "kr": "추적 클러스터가 어디에 붙느냐가 그 클러스터가 안고 가는 STA의 크기를 결정합니다. "
                  "근복(수축 시 부풀어 오르는 살 많은 부위)과 관절선 근처 분절 끝(피부가 가장 많이 "
                  "미끄러지는 곳)을 피하세요. 대퇴 클러스터는 원위-외측에, 정강이 클러스터는 피부 "
                  "밑에 뼈가 가까운 전외측 경골면 위에 두세요. 강체 마커 플레이트(단단한 셸 위 "
                  "클러스터)는 한 덩어리로 움직여, 헐겁게 붙은 피부 마커 4개보다 클러스터 강성을 "
                  "잘 유지합니다.",
        },
        "points": {
            "en": [
                "Avoid muscle bellies and the joint-line ends of the segment.",
                "Thigh = distal-lateral; shank = antero-lateral tibial surface (bone close).",
                "Prefer a rigid marker plate over loose skin markers.",
            ],
            "kr": [
                "근복과 관절선 쪽 분절 끝을 피하세요.",
                "대퇴 = 원위-외측; 정강이 = 전외측 경골면(뼈 가까움).",
                "헐거운 피부 마커보다 강체 마커 플레이트를 권장.",
            ],
        },
    },
    {
        "title": {
            "en": "Part 6 — The realistic ceiling (an honest operating guide, Table B)",
            "kr": "Part 6 — 현실적 천장 (정직한 운용 지침, Table B)",
        },
        "body": {
            "en": "Even with a standard marker set the three planes are not equally "
                  "trustworthy. The table grades each joint by plane. Flexion/extension "
                  "(sagittal) is reliable everywhere; abduction/adduction is good at "
                  "the hip and shoulder but weak at the knee and (without foot ML "
                  "markers) at the ankle; internal/external rotation and foot "
                  "inversion/eversion remain the WEAKEST channels even with a standard "
                  "set. Push them as high as possible with a functional axis, but "
                  "interpret the residual by left–right comparison, trend and "
                  "repeatability — not by its absolute value.",
            "kr": "표준 마커셋을 써도 세 평면의 신뢰도는 같지 않습니다. 아래 표가 관절별·평면별로 "
                  "등급을 매깁니다. 굴곡/신전(시상면)은 어디서나 신뢰 가능하고, 외전/내전은 고관절·"
                  "어깨에서 양호하지만 무릎과 (발 ML 마커가 없으면) 발목에서 약합니다; 내·외회전"
                  "(IE)과 발 내번/외번은 표준 마커셋으로도 여전히 가장 약한 채널입니다. functional "
                  "축으로 최대한 끌어올리되, 남는 잔차는 절대값이 아니라 좌우 비교·경향(trend)·"
                  "반복성으로 해석하세요.",
        },
        "table": "B",
        "caption": {
            "en": "Upper- and lower-limb flexion/abduction read out well; ROTATION (IE) "
                  "and foot inversion/eversion stay the weakest channels even with a "
                  "standard marker set. Lift them with a functional axis where you can, "
                  "and read the residual as left–right comparison, trend and "
                  "repeatability — not as an absolute value.",
            "kr": "상·하지 굴곡/외전은 잘 나오고, 회전(IE)·발 내번외번은 표준 마커셋으로도 여전히 "
                  "가장 약한 채널입니다. 가능한 곳에서는 functional 축으로 끌어올리고, 남는 잔차는 "
                  "절대값이 아니라 좌우 비교·경향(trend)·반복성으로 해석하세요.",
        },
    },
    {
        "title": {
            "en": "Part 7 — BalanceAnalyzer mapping",
            "kr": "Part 7 — BalanceAnalyzer 매핑",
        },
        "body": {
            "en": "How this maps to BalanceAnalyzer today. The current default set has "
                  "a 2-marker foot (heel + toe), so ankle AB/IE are tagged 'low'. "
                  "Already implemented: the CAST anatomical-frame handling on thigh and "
                  "shank (which normalised hip/knee rotation), a knee-IE 'moderate' "
                  "reliability tag, and automatic cross-talk diagnosis. To cover the "
                  "remaining planes fully you would add two capture-protocol pieces: "
                  "paired medial+lateral markers ON THE FOOT (a multi-segment foot) and "
                  "a functional calibration trial. The reliability badges you see in "
                  "the app map one-to-one onto this manual.",
            "kr": "이것이 현재 BalanceAnalyzer에 어떻게 대응하는지입니다. 현재 기본 셋은 발 마커 "
                  "2개(heel + toe)라서 발목 AB/IE가 'low'로 표기됩니다. 이미 구현된 것: thigh/"
                  "shank의 CAST 분절좌표계 처리(hip/knee 회전 정상화), 무릎 IE 'moderate' 신뢰도 "
                  "표기, cross-talk 자동 진단. 남은 평면을 완전히 커버하려면 촬영 프로토콜 두 가지를 "
                  "추가합니다: '발 위' 내·외측 마커쌍(멀티세그먼트 발)과 functional 보정 trial. "
                  "앱에 표시되는 신뢰도 배지는 이 매뉴얼과 1:1로 대응합니다.",
        },
        "points": {
            "en": [
                "Now: 2-marker foot → ankle AB/IE 'low'.",
                "Implemented: thigh/shank CAST, knee-IE 'moderate', auto cross-talk diagnosis.",
                "To add: paired medial/lateral foot markers (multi-segment foot) + a functional trial.",
            ],
            "kr": [
                "현재: 발 2마커 → 발목 AB/IE 'low'.",
                "구현됨: thigh/shank CAST, 무릎 IE 'moderate', cross-talk 자동 진단.",
                "추가할 것: 발 위 내·외측 마커쌍(멀티세그먼트 발) + functional 보정 trial.",
            ],
        },
    },
]


# TABLE A — standard marker set per segment. Each row: segment, axis-defining
# (static-only) markers, tracking cluster, joint centre/axis, three-plane
# reliability. ``**bold**`` spans mark the rotation-axis essentials (paired
# markers) and are rendered as <b>…</b>.
MARKERSET_TABLE_A = {
    "headers": {
        "en": ["Segment", "Axis-defining (static-only)", "Tracking cluster (dynamic)",
               "Joint centre / axis", "3-plane reliability"],
        "kr": ["분절", "축 정의 (static 전용)", "추적 클러스터 (동적)",
               "관절중심 / 축", "3평면 신뢰도"],
    },
    "rows": [
        {
            "en": ["Pelvis", "ASIS L/R + PSIS L/R (or sacrum SACR)", "Same 4 points (rigid)",
                   "Hip centre = SCoRE (functional) or regression (Harrington)", "Good"],
            "kr": ["골반 (Pelvis)", "ASIS L/R + PSIS L/R (또는 천골 SACR)", "동일 4점 (강체)",
                   "Hip centre = SCoRE(functional) 또는 회귀(Harrington)", "양호"],
        },
        {
            "en": ["Thigh", "**medial + lateral femoral epicondyle**",
                   "4-marker distal-lateral thigh cluster",
                   "Knee flexion axis = transepicondylar (or functional SARA); hip centre from pelvis",
                   "FE/AB good, **IE weakest**"],
            "kr": ["대퇴 (Thigh)", "**내·외측 대퇴상과 (med/lat femoral epicondyle)**",
                   "대퇴 원위-외측 4마커 클러스터",
                   "무릎 굴신축 = transepicondylar(또는 functional SARA); hip centre는 골반에서",
                   "FE/AB 양호, **IE 가장 약함**"],
        },
        {
            "en": ["Shank", "**medial + lateral malleolus**",
                   "4-marker antero-lateral shank cluster",
                   "Ankle axis = transmalleolar (or functional)", "FE good, IE/inversion weak"],
            "kr": ["하퇴 (Shank)", "**내·외측 복사뼈 (med/lat malleolus)**",
                   "정강이 전외측 4마커 클러스터",
                   "발목축 = transmalleolar(또는 functional)", "FE 양호, IE/내번 약함"],
        },
        {
            "en": ["Foot", "Single segment = FE only reliable. Multi-segment (OFM/Rizzoli): "
                   "**calcaneus medial + lateral (rear-foot), 1st + 5th metatarsal head "
                   "(fore-foot), hallux**",
                   "Markers on the foot", "—",
                   "**inv/ev needs medial + lateral markers ON THE FOOT**"],
            "kr": ["발 (Foot)", "단일분절 = FE만 신뢰. 다분절(OFM/Rizzoli): "
                   "**후족 종골 내·외측, 전족 1·5중족골두, 무지(hallux)**",
                   "발 위 마커", "—",
                   "**inv/ev는 발 위 내·외측 마커가 있어야 가능**"],
        },
        {
            "en": ["Trunk / Thorax", "C7, T10 (or T8), IJ (jugular notch), PX (xiphoid process)",
                   "Same", "—", "Good"],
            "kr": ["흉부 (Trunk/Thorax)", "C7, T10(또는 T8), IJ(흉골상절흔), PX(검상돌기)",
                   "동일", "—", "양호"],
        },
        {
            "en": ["Upper arm", "**medial + lateral humeral epicondyle**",
                   "Lateral upper-arm cluster", "Shoulder centre = SCoRE", "IE weak"],
            "kr": ["상완 (Upper arm)", "**내·외측 상완상과 (med/lat humeral epicondyle)**",
                   "상완 외측 클러스터", "Shoulder centre = SCoRE", "IE 약함"],
        },
        {
            "en": ["Forearm", "radial + ulnar styloid process", "Cluster", "Elbow axis", "—"],
            "kr": ["전완 (Forearm)", "요골·척골 경상돌기 (radial/ulnar styloid)", "클러스터",
                   "팔꿈치축", "—"],
        },
        {
            "en": ["Hand", "Same principle (paired markers + cluster)", "—", "—", "—"],
            "kr": ["손 (Hand)", "동일 원리 (양측 쌍 + 클러스터)", "—", "—", "—"],
        },
    ],
}


# TABLE B — realistic per-plane reliability ceiling. Each row: joint, then a
# rating for FE / AB-AD / IE. ``**bold**`` flags the weakest cell.
MARKERSET_TABLE_B = {
    "headers": {
        "en": ["Joint", "FE (sagittal / flexion)", "AB/AD (frontal)", "IE (transverse / rotation)"],
        "kr": ["관절", "FE (시상/굴신)", "AB/AD (전두)", "IE (횡단/회전)"],
    },
    "rows": [
        {
            "en": ["Hip", "High", "High", "Moderate (standard set + functional)"],
            "kr": ["Hip", "High", "High", "Moderate (표준셋 + functional)"],
        },
        {
            "en": ["Knee", "High", "Moderate", "**Low–Moderate (weakest)**"],
            "kr": ["Knee", "High", "Moderate", "**Low~Moderate (가장 약함)**"],
        },
        {
            "en": ["Ankle", "High", "Low (without foot ML markers)", "Low"],
            "kr": ["Ankle", "High", "Low (발 ML 마커 없으면)", "Low"],
        },
        {
            "en": ["Shoulder", "High", "High", "Moderate"],
            "kr": ["Shoulder", "High", "High", "Moderate"],
        },
        {
            "en": ["Elbow", "High", "—", "Moderate"],
            "kr": ["Elbow", "High", "—", "Moderate"],
        },
    ],
}


# Part 8 — References (14), rendered hanging-indent with a leading [tag].
MARKERSET_REFS = [
    {"tag": "CAST",
     "cite": "Cappozzo A, Catani F, Della Croce U, Leardini A (1995). Position and "
             "orientation in space of bones during movement: anatomical frame "
             "definition and determination. Clinical Biomechanics 10(4):171–178."},
    {"tag": "stereophotogrammetry",
     "cite": "Cappozzo A, Della Croce U, Leardini A, Chiari L (2005). Human movement "
             "analysis using stereophotogrammetry. Part 1: theoretical background. "
             "Gait & Posture 21(2):186–196."},
    {"tag": "STA",
     "cite": "Leardini A, Chiari L, Della Croce U, Cappozzo A (2005). Human movement "
             "analysis using stereophotogrammetry. Part 3: soft-tissue artifact "
             "assessment and compensation. Gait & Posture 21(2):212–225."},
    {"tag": "landmark misplacement",
     "cite": "Della Croce U, Leardini A, Chiari L, Cappozzo A (2005). Human movement "
             "analysis using stereophotogrammetry. Part 4: anatomical landmark "
             "misplacement and its effects on joint kinematics. Gait & Posture "
             "21(2):226–237."},
    {"tag": "ISB lower",
     "cite": "Wu G, Siegler S, Allard P, et al. (2002). ISB recommendation on "
             "definitions of joint coordinate system of various joints for the "
             "reporting of human joint motion — Part I: ankle, hip, and spine. "
             "Journal of Biomechanics 35(4):543–548."},
    {"tag": "ISB upper",
     "cite": "Wu G, van der Helm FCT, Veeger HEJ, et al. (2005). ISB recommendation "
             "on definitions of joint coordinate systems of various joints for the "
             "reporting of human joint motion — Part II: shoulder, elbow, wrist and "
             "hand. Journal of Biomechanics 38(5):981–992."},
    {"tag": "SCoRE",
     "cite": "Ehrig RM, Taylor WR, Duda GN, Heller MO (2006). A survey of formal "
             "methods for determining the centre of rotation of ball joints. Journal "
             "of Biomechanics 39(15):2798–2809."},
    {"tag": "SARA",
     "cite": "Ehrig RM, Taylor WR, Duda GN, Heller MO (2007). A survey of formal "
             "methods for determining functional joint axes. Journal of Biomechanics "
             "40(10):2150–2157."},
    {"tag": "AXIS",
     "cite": "Schwartz MH, Rozumalski A (2005). A new method for estimating joint "
             "parameters from motion data. Journal of Biomechanics 38(1):107–116."},
    {"tag": "cross-talk sensitivity",
     "cite": "Piazza SJ, Cavanagh PR (2000). Measurement of the screw-home motion of "
             "the knee is sensitive to errors in axis alignment. Journal of "
             "Biomechanics 33(8):1029–1034."},
    {"tag": "hip rotation profile",
     "cite": "Baker R, Finney L, Orr J (1999). A new approach to determine the hip "
             "rotation profile from clinical gait analysis data. Human Movement "
             "Science 18:655–667."},
    {"tag": "cross-talk correction",
     "cite": "Baudet A, Morisset C, d'Athis P, Maillefert J-F, Casillas J-M, Ornetti "
             "P, Laroche D (2014). Cross-talk correction method for knee kinematics in "
             "gait analysis using PCA. PLoS One 9(7):e102098."},
    {"tag": "Oxford Foot Model",
     "cite": "Stebbins J, Harrington M, Thompson N, Zavatsky A, Theologis T (2006). "
             "Repeatability of a model for measuring multi-segment foot kinematics in "
             "children (Oxford Foot Model). Gait & Posture 23(4):401–410."},
    {"tag": "Rizzoli/IOR foot",
     "cite": "Leardini A, Benedetti MG, Berti L, Bettinelli D, Nativo R, Giannini S "
             "(2007). Rear-foot, mid-foot and fore-foot motion during the stance phase "
             "of gait. Gait & Posture 25(3):453–462."},
]

# Visual3D documentation links (clickable). setOpenExternalLinks on the labels.
MARKERSET_LINKS = [
    {"label": "Visual3D — Functional Joints",
     "url": "https://wiki.has-motion.com/doku.php?id=visual3d:documentation:modeling:functional_joints:functional_joints"},
    {"label": "Visual3D — Segment Overview",
     "url": "https://has-motion.com/wiki/doku.php?id=visual3d:documentation:modeling:segments:segment_overview"},
    {"label": "Visual3D — Marker Sets",
     "url": "https://has-motion.com/wiki/doku.php?id=visual3d:documentation:modeling:marker_sets:marker_sets_overview"},
]


class MarkerSetManualDialog(QDialog):
    """Collapsible, bilingual 'Standard Marker Set — A Researcher's Reference'.

    Mirrors MarkersHelpDialog (lang toggle, scroll area, _Collapsible folds,
    S colour tokens) but renders the per-segment marker set (Table A) and the
    reliability ceiling (Table B) as RichText <table>s, and closes with the
    14-reference list + three Visual3D documentation links.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Marker Set Manual")
        self.setModal(False)
        self.resize(640, 600)
        self._lang = "en"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:16px;font-weight:700;")
        head.addWidget(self._title_lbl)
        head.addStretch()
        self._lang_btn = QPushButton()
        self._lang_btn.setObjectName("toggle-btn")
        self._lang_btn.setFixedHeight(22)
        self._lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lang_btn.clicked.connect(self._toggle_lang)
        head.addWidget(self._lang_btn)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;border:none;")
        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._col = QVBoxLayout(self._inner)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(2)
        scroll.setWidget(self._inner)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)
        self._populate()

    def _toggle_lang(self):
        self._lang = "kr" if self._lang == "en" else "en"
        self._populate()

    def _populate(self):
        lang = self._lang
        self._title_lbl.setText(
            "Standard Marker Set — A Researcher's Reference" if lang == "en"
            else "표준 마커셋 매뉴얼 (연구자용 레퍼런스)"
        )
        self._lang_btn.setText("KOR" if lang == "en" else "EN")
        while self._col.count():
            item = self._col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        style = f"color:{S.TEXT_PRIMARY};font-size:13px;font-weight:700;"
        for doc in MARKERSET_DOCS:
            sec = _Collapsible(doc["title"][lang], style, indent=12)
            sec.add(self._section_body(doc, lang))
            self._col.addWidget(sec)

        # Part 8 — References + Visual3D links as the final foldable entry.
        refs_title = "Part 8 — References" if lang == "en" else "Part 8 — 참고문헌 (References)"
        refs = _Collapsible(refs_title, style, indent=12)
        refs.add(self._refs_card(lang))
        self._col.addWidget(refs)

        self._col.addStretch(1)

    def _card(self):
        """A bordered content card (object-name scoped so the border does not
        cascade onto child labels), matching the other help dialogs."""
        card = QFrame()
        card.setObjectName("help-card")
        card.setStyleSheet(
            f"QFrame#help-card {{ background:{S.BG_PANEL}; border:1px solid {S.BORDER};"
            " border-radius:6px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        return card, lay

    def _section_body(self, doc, lang):
        """Body paragraph + optional table + caption + optional bullet points."""
        card, lay = self._card()

        body = QLabel(doc["body"][lang])
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:12px;border:none;line-height:150%;")
        lay.addWidget(body)

        table_key = doc.get("table")
        if table_key:
            spec = MARKERSET_TABLE_A if table_key == "A" else MARKERSET_TABLE_B
            tbl = QLabel(self._table_html(spec, lang))
            tbl.setTextFormat(Qt.TextFormat.RichText)
            tbl.setWordWrap(True)
            tbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            tbl.setStyleSheet("border:none;background:transparent;")
            lay.addWidget(tbl)

        caption = doc.get("caption", {}).get(lang)
        if caption:
            cap = QLabel(caption)
            cap.setWordWrap(True)
            cap.setStyleSheet(
                f"color:{S.TEXT_SECONDARY};font-size:11px;border:none;"
                "font-style:italic;line-height:150%;"
            )
            lay.addWidget(cap)

        for p in doc.get("points", {}).get(lang, []):
            row = QLabel(f"•  {p}")
            row.setWordWrap(True)
            row.setStyleSheet(
                f"color:{S.TEXT_SECONDARY};font-size:11px;border:none;line-height:150%;"
                "padding-left:4px;"
            )
            lay.addWidget(row)
        return card

    @staticmethod
    def _md_bold(text):
        """Render ``**span**`` markers as <b>span</b> (the only inline markup
        these tables use). Splitting on the literal token keeps it simple and
        safe — the cell text carries no other HTML."""
        parts = text.split("**")
        out = []
        for i, chunk in enumerate(parts):
            out.append(f"<b>{chunk}</b>" if i % 2 == 1 else chunk)
        return "".join(out)

    def _table_html(self, spec, lang):
        """Build a RichText <table> from a table spec, colours from S tokens."""
        headers = spec["headers"][lang]
        head_bg = S.BG_INPUT
        border = S.BORDER
        head_fg = S.TEXT_PRIMARY
        cell_fg = S.TEXT_PRIMARY
        th = "".join(
            f"<th style='border:1px solid {border};padding:5px 7px;"
            f"background:{head_bg};color:{head_fg};text-align:left;'>{h}</th>"
            for h in headers
        )
        rows_html = [f"<tr>{th}</tr>"]
        for row in spec["rows"]:
            cells = "".join(
                f"<td style='border:1px solid {border};padding:5px 7px;"
                f"color:{cell_fg};vertical-align:top;'>{self._md_bold(c)}</td>"
                for c in row[lang]
            )
            rows_html.append(f"<tr>{cells}</tr>")
        return (
            "<table border='1' cellspacing='0' cellpadding='0' "
            f"style='border-collapse:collapse;border:1px solid {border};"
            "font-size:11px;'>" + "".join(rows_html) + "</table>"
        )

    def _refs_card(self, lang):
        """The 14-reference hanging-indent list + Visual3D documentation links."""
        card, lay = self._card()
        lay.setSpacing(7)

        for ref in MARKERSET_REFS:
            html = (
                f"<span style='color:{S.ACCENT_TEAL};font-weight:600;'>[{ref['tag']}]</span> "
                f"<span style='color:{S.TEXT_PRIMARY};'>{ref['cite']}</span>"
            )
            lbl = QLabel(html)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setStyleSheet("font-size:11px;border:none;line-height:150%;")
            lay.addWidget(lbl)

        links_hdr = QLabel("Visual3D documentation" if lang == "en" else "Visual3D 문서")
        links_hdr.setStyleSheet(
            f"color:{S.TEXT_SECONDARY};font-size:11px;font-weight:600;border:none;"
            "padding-top:4px;"
        )
        lay.addWidget(links_hdr)
        for link in MARKERSET_LINKS:
            lbl = QLabel(f"<a href='{link['url']}' style='color:{S.ACCENT_PURPLE};'>{link['label']}</a>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setOpenExternalLinks(True)
            lbl.setStyleSheet("font-size:11px;border:none;line-height:150%;")
            lay.addWidget(lbl)
        return card

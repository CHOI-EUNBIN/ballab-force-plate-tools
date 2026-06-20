# COP Metrics Guide

This document explains the center-of-pressure (COP) metrics currently calculated by Balancelab Force Plate Tools. The formulas below are based on the current implementation in `core/metrics.py`.

## Input Data

The analysis uses COP time-series data from a selected analysis window:

- `COP_AP`: anterior-posterior COP position, in millimeters
- `COP_ML`: medial-lateral COP position, in millimeters
- `fs`: sampling frequency, in Hz
- `n`: number of samples in the selected analysis window

For several metrics, the mean is removed first:

```text
AP_centered = COP_AP - mean(COP_AP)
ML_centered = COP_ML - mean(COP_ML)
duration = (n - 1) / fs
```

## Metric Summary

| Metric | Unit | Meaning |
|---|---:|---|
| RMS AP | mm | Typical AP deviation around the mean COP position |
| RMS ML | mm | Typical ML deviation around the mean COP position |
| Range AP | mm | Total AP excursion within the selected window |
| Range ML | mm | Total ML excursion within the selected window |
| Mean AP | mm | Average AP COP position |
| Mean ML | mm | Average ML COP position |
| 95% Ellipse area | mm^2 | Area of the chi-square-based 95% COP ellipse |
| Sway path length | mm | Total COP path distance across the selected window |
| Mean velocity | mm/s | Average COP travel speed |
| Mean power freq AP | Hz | Power-weighted average AP sway frequency |
| Mean power freq ML | Hz | Power-weighted average ML sway frequency |
| Median freq AP | Hz | AP frequency where cumulative spectral power reaches 50% |
| Median freq ML | Hz | ML frequency where cumulative spectral power reaches 50% |

## Position and Excursion Metrics

### RMS AP and RMS ML

RMS describes the typical size of COP deviation around the mean position.

```text
RMS_AP = sqrt(mean(AP_centered^2))
RMS_ML = sqrt(mean(ML_centered^2))
```

Interpretation:

- Higher RMS means larger COP variability in that direction.
- RMS AP focuses on anterior-posterior sway.
- RMS ML focuses on medial-lateral sway.

### Range AP and Range ML

Range measures the full excursion from the minimum to the maximum COP position.

```text
Range_AP = max(COP_AP) - min(COP_AP)
Range_ML = max(COP_ML) - min(COP_ML)
```

Interpretation:

- Higher range means the COP covered a wider positional span.
- Range can be sensitive to brief outliers or transient movement.

### Mean AP and Mean ML

Mean position describes the average COP location within the selected window.

```text
Mean_AP = mean(COP_AP)
Mean_ML = mean(COP_ML)
```

Interpretation:

- These values describe where the COP was centered in the selected range.
- They are useful for comparing posture or offset between trials, but they are not sway magnitude metrics by themselves.
- The interpretation of positive and negative AP/ML values depends on the axis convention and sign correction settings used during recording or analysis.

## Spatial COP Distribution

### 95% Ellipse Area

The 95% ellipse area estimates the area of the chi-square-based 95% COP ellipse in AP-ML space. Balancelab calculates the covariance matrix of centered AP and ML data, then uses the 95% chi-square value for two dimensions.

```text
cov = covariance([AP_centered, ML_centered])
lambda_1, lambda_2 = eigenvalues(cov)
chi2_95 = chi_square_inverse_cdf(0.95, df=2)

Ellipse_area = pi * chi2_95 * sqrt(lambda_1 * lambda_2)
```

Interpretation:

- Larger ellipse area means COP positions are more widely distributed.
- This is useful as a compact two-dimensional measure of postural sway.
- The plotted ellipse uses the same covariance principle, displayed in ML-by-AP space.

## Path and Velocity Metrics

### Sway Path Length

Sway path length is the total distance traveled by COP over time.

```text
Sway_path_length = sum(
    sqrt(diff(COP_AP)^2 + diff(COP_ML)^2)
)
```

Interpretation:

- Higher path length means the COP traveled farther during the selected window.
- Unlike range, it accounts for the complete trajectory, not just min-to-max distance.

### Mean Velocity

Mean velocity is the total COP path length divided by analysis duration.

```text
duration = (n - 1) / fs
Mean_velocity = Sway_path_length / duration
```

Interpretation:

- Higher mean velocity means faster COP movement.
- This can increase even if the overall range is not large, as long as the COP moves frequently within the area.
- Because sway path length is calculated from `diff()` intervals, duration is based on the `n - 1` sample intervals between the first and last samples.

## Frequency Metrics

Frequency metrics are calculated separately for AP and ML directions using the centered COP signal.

Balancelab computes the one-sided FFT frequency bins and spectral power:

```text
freqs = rfftfreq(n, 1 / fs)
power = abs(rfft(centered_signal))^2
```

The zero-frequency component is excluded before frequency metrics are calculated.

### Mean Power Frequency AP and ML

Mean power frequency is the power-weighted average frequency.

```text
Mean_power_frequency = sum(freq * power) / sum(power)
```

Interpretation:

- Higher values indicate that more sway power is concentrated at higher frequencies.
- AP and ML are calculated independently.

### Median Frequency AP and ML

Median frequency is the frequency where cumulative spectral power reaches 50% of total power.

```text
cumulative_power = cumulative_sum(power)
Median_frequency = first freq where cumulative_power >= total_power * 0.5
```

Interpretation:

- Half of the signal power lies below this frequency and half lies above it.
- This helps summarize the frequency distribution without relying only on the average.

## Notes and Limitations

- Metrics are calculated only for the selected analysis window.
- Filtering settings affect analysis results when filtering is enabled in the app.
- COP units are assumed to be millimeters.
- Frequency metrics depend on sampling rate and selected window length.
- Frequency estimates are based on the current FFT implementation and may be affected by window length, filtering, and non-stationary sway behavior.
- Very short analysis windows may produce unstable frequency metrics.
- Range metrics can be sensitive to outliers.
- These metrics are descriptive analysis outputs; interpretation should be made in the context of the study protocol and measurement setup.

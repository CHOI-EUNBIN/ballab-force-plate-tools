# Synthetic Demo Data

This folder contains synthetic CSV trials for testing the Balancelab Force Plate Tools interface.

The demo files are generated signals only. They do not contain participant, patient, or experimental data.

## Files

- `synthetic_trial_001.csv`
- `synthetic_trial_002.csv`
- `synthetic_trial_003.csv`

Each file contains the columns expected by the Analyze tab:

```text
sample,time_s,Fx,Fy,Fz,Mx,My,Mz,COP_AP,COP_ML,fs
```

Use these files to test:

- CSV loading
- Trial replay
- COP and force visualization
- Metric calculation
- Event marking
- Excel export

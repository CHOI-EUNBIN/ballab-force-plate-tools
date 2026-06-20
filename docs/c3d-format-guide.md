# C3D File Support

## Overview
BalanceAnalyzer now supports C3D files for motion capture data analysis. C3D is a widely used format for storing biomechanical data from motion capture systems like Qualisys QTM, VICON, etc.

## Requirements
- **Library**: `ezc3d` (added to requirements.txt)
- **File Format**: C3D (v2 or v3)
- **Data**: Must contain force plate data in analog channels

## Supported Channel Names

The C3D reader automatically detects common channel naming patterns:

### Force Components (Fx, Fy, Fz)
- `Fx`, `Fy`, `Fz` (standard)
- `Plate1Fx`, `Plate1Fy`, `Plate1Fz` (with plate number)
- `Force1X`, `Force1Y`, `Force1Z` (alternative naming)
- `FX1`, `FY1`, `FZ1` (uppercase variants)

### Center of Pressure (COP)
- `COP_AP`, `COP_ML` (if directly available)
- `CoPX`, `CoPY` / `COPx`, `COPy` (alternative naming)
- **Automatic Calculation**: If COP not available, it's calculated from moments: COP = Moment / Fz

### Moments (Mx, My) - for COP calculation
- `Mx`, `My` (standard)
- `Moment1X`, `Moment1Y`
- `MX1`, `MY1`

## File Preparation Guidelines

### From QTM (Qualisys)
1. Export force plate data from QTM to C3D format
2. Ensure force data is included in analog channels
3. Supported export options:
   - Force data: Fx, Fy, Fz components
   - Moments: Mx, My (optional, for COP calculation if COP not available)
   - COP values (optional): CoPx, CoPy

### Data Requirements
- **Minimum**: Fz (vertical force) is required
- **Recommended**: Fx, Fy, COP_AP, COP_ML
- **Sampling Rate**: Auto-detected from file (typically 100-1000 Hz)

## How to Load C3D Files

1. Open the **Analysis** tab
2. Click **"Load"** button
3. Select file format: **"C3D Files (*.c3d)"** or **"All Supported Files"**
4. Select one or more C3D files
5. Files will be automatically converted to the internal format

## Data Conversion

When loading a C3D file, the reader:
1. Extracts force plate analog channels
2. Automatically detects channel naming patterns
3. Calculates COP if not available: `COP = Moment / Fz`
4. Synchronizes all data to the same time base
5. Outputs data in the format expected by the analyzer

## Troubleshooting

### "No analog data found"
- C3D file doesn't contain force plate data
- Verify the file was exported with force data enabled

### "No Fz data found"
- Vertical force (Fz) is missing from the file
- This is the minimum required data

### "No Fx/Fy data found" (warning only)
- Horizontal forces not available but analysis can continue
- Analysis will work with vertical force (Fz) and COP

### Channels not recognized
- Check channel names in your C3D file
- Most common naming patterns are supported automatically
- If needed, manually pre-process with specialized C3D tools

## Mixed Format Analysis

You can load both CSV and C3D files in the same analysis session:
- Load multiple CSV files
- Load one or more C3D files
- All data will be analyzed together
- File type is automatically detected from extension

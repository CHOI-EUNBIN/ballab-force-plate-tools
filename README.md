# BALLAB Force Plate Tools

Desktop software for recording, replaying, visualizing, and analyzing force plate data for balance and center-of-pressure (COP) research workflows.

BALLAB Force Plate Tools is built for laboratory use with AMTI-style force plate signals and QTM streaming. The application separates live recording from offline analysis so recorded trials can be reviewed, compared, marked with events, analyzed, and exported without including raw research data in the repository.

## Screenshots

Screenshots for portfolio and release pages can be placed in:

```text
assets/screenshots/
```

Suggested files:

```text
assets/screenshots/record-tab.png
assets/screenshots/analyze-tab.png
assets/screenshots/settings-tab.png
```

No participant data or real research trial files should be committed with screenshots.

## Current Features

- Live force plate recording through QTM connection.
- Record tab focused on data collection and saving recorded trials to CSV.
- Analyze tab for loading recorded CSV files and replaying the selected trial.
- COP visualization:
  - COP trajectory
  - COP time series
  - COP AP and COP ML traces
  - 95% ellipse visualization for analyzed data
- Force visualization in Analyze:
  - Force X
  - Force Y
  - Force Z
- Selectable graph panels with collapsible Graph, Metrics, and Event sections.
- Analysis range selection using a time slider.
- Metric selection and analysis execution for checked files.
- Event detection and event marker visualization.
- Excel export for analysis results, descriptive statistics, included files, and events.
- Settings for live axis sign correction and analysis filter options.
- Windows build scripts and PyInstaller configuration.

## Planned Features

These items are planned or reserved and should not be treated as completed functionality:

- More formal validation against known force plate datasets.
- Example screenshots using synthetic or anonymized data.
- User documentation for the analysis metrics.
- Expanded export templates for reporting.
- Additional hardware connection presets.
- Automated tests for CSV parsing, event detection, and metric calculations.
- Optional sample dataset generated from synthetic data only.

## Project Structure

```text
.
|-- main.py                 # Application entry point
|-- core/                   # Data processing, metrics, QTM client, axis settings
|-- ui/                     # PyQt6 tabs, layouts, plotting, and styling
|-- assets/                 # App icons and visual assets
|   `-- screenshots/        # Placeholder for portfolio/release screenshots
|-- requirements.txt        # Python dependencies
|-- setup_dev.bat           # Windows development environment setup
|-- run_dev.bat             # Run the app from the local virtual environment
|-- build.bat               # Windows build helper
|-- build_macos.sh          # macOS build helper
|-- BALLAB.spec             # PyInstaller spec file
`-- installer.iss           # Inno Setup installer script
```

## Data Privacy

This repository should contain source code, configuration, documentation, and app assets only.

Do not commit:

- Raw force plate recordings
- Participant or patient data
- Exported analysis workbooks
- Local QTM/session logs
- Built executables or installer outputs

The `.gitignore` file excludes common raw data, output, virtual environment, and build artifact paths.

## Requirements

- Windows is the primary development target.
- Python 3.11 or newer is recommended.
- QTM is required for live streaming workflows.
- Python dependencies are listed in `requirements.txt`.

## Running Locally

From PowerShell:

```powershell
git clone https://github.com/CHOI-EUNBIN/ballab-force-plate-tools.git
cd ballab-force-plate-tools
.\setup_dev.bat
.\run_dev.bat
```

To pass a custom QTM host IP:

```powershell
.\run_dev.bat --ip 192.168.0.10
```

## Building

Windows build:

```powershell
.\build.bat
```

Build outputs are generated locally and should not be committed to GitHub.

## Repository Status

This project is under active development. The current focus is a practical desktop workflow for force plate balance recording, COP visualization, trial replay, event marking, and analysis export.

# Development Workflow

Use this workflow while editing and testing the app.

## First-time setup

Run once:

```bat
setup_dev.bat
```

This creates `.venv` and installs the packages from `requirements.txt`.

## Run while developing

After editing code, run:

```bat
run_dev.bat
```

You can also run directly:

```bat
.venv\Scripts\python.exe main.py
```

For a QTM IP:

```bat
run_dev.bat --ip 192.168.0.10
```

## Build for distribution

Only build when you need an exe:

```bat
build.bat
```

`build.bat` uses `.venv` when it exists, so the build environment matches the development environment.

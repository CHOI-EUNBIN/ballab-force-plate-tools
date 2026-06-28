import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _import_or_exit(module_name, package_hint):
    try:
        return __import__(module_name, fromlist=["*"])
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        print()
        print(f"[ERROR] Missing Python package: {module_name}")
        print()
        print("Install the development environment first:")
        print("  setup_dev.bat")
        print()
        print("Or install packages into the current Python:")
        print(f"  {sys.executable} -m pip install {package_hint}")
        print()
        raise SystemExit(1) from exc


def main():
    parser = argparse.ArgumentParser(description="Balancelab")
    parser.add_argument("--ip", default="127.0.0.1",
                        help="QTM host IP (default: 127.0.0.1)")
    parser.add_argument("project", nargs="?", default=None,
                        help="Optional .ballab project file to open on launch")
    args = parser.parse_args()

    qt_widgets = _import_or_exit("PyQt6.QtWidgets", "-r requirements.txt")
    qt_gui = _import_or_exit("PyQt6.QtGui", "-r requirements.txt")
    QApplication = qt_widgets.QApplication
    QIcon = qt_gui.QIcon

    # Logging: capture calculation errors to a file even when the UI degrades
    # gracefully (the analysis paths swallow exceptions). Tell the user the path
    # so it can be shared for diagnosis.
    import logging
    from core.logging_setup import setup_logging
    log_file = setup_logging()
    print(f"[Balancelab] log file: {log_file}")
    # Route Qt's own warnings into the same log.
    from PyQt6.QtCore import qInstallMessageHandler
    qInstallMessageHandler(lambda mode, ctx, msg: logging.getLogger("qt").warning(msg))

    from ui.main_window import MainWindow, resource_path

    app = QApplication(sys.argv)
    app.setApplicationName("Balancelab")
    # Block mouse-wheel value changes on every spin/combo box app-wide (a single
    # shared event filter) — scrolling a panel must never silently edit a value.
    from ui.components.wheel_guard import app_guard
    app.installEventFilter(app_guard())
    app.setWindowIcon(QIcon(resource_path("assets/ballab_icon_master_1024_transparent.png")))

    # Animated logo splash shown while the (heavy) main window is built. The
    # logo fades in while scaling up, holds for a minimum time, then fades out.
    # A translucent background means only the transparent-PNG logo is visible —
    # it also covers the brief white flash before the UI paints.
    from PyQt6.QtCore import QTimer
    from ui.splash import AnimatedSplash
    QPixmap = qt_gui.QPixmap

    logo = QPixmap(resource_path("assets/ballab_icon_master_1024_transparent.png"))
    splash = None
    if not logo.isNull():
        splash = AnimatedSplash(logo)
        splash.show()
        splash.start()
        app.processEvents()

    state = {}

    def build():
        win = MainWindow(qtm_ip=args.ip)
        state["win"] = win                      # keep a reference past this scope
        win.show()
        if args.project and os.path.isfile(args.project):
            win.open_project_path(args.project)
        if splash is not None:
            splash.finish(win)

    if splash is not None:
        # Defer the heavy build so the event loop runs first and the intro
        # animation paints a few frames before the build briefly blocks it.
        QTimer.singleShot(50, build)
    else:
        build()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

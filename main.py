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
    from ui.main_window import MainWindow, resource_path

    app = QApplication(sys.argv)
    app.setApplicationName("Balancelab")
    app.setWindowIcon(QIcon(resource_path("assets/ballab_icon_master_1024_transparent.png")))
    win = MainWindow(qtm_ip=args.ip)
    win.show()
    if args.project and os.path.isfile(args.project):
        win.open_project_path(args.project)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

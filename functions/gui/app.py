"""GUI entry point: `python -m functions.gui.app [--minimal]` (scripts/run_pipeline.sh calls this)."""
import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_pipeline", description="RORA pipeline GUI")
    parser.add_argument("--minimal", action="store_true",
                        help="no debug checkpoints, no live viewport during compute, terminal-only log")
    args = parser.parse_args(argv)
    try:
        from PySide6.QtWidgets import QApplication

        from functions.gui.window import MainWindow
    except ImportError as e:
        print(f"[error]: the GUI needs PySide6 and VTK's Qt support ({e}). Run: uv pip install -r requirements.txt")
        return 1
    app = QApplication(sys.argv[:1])
    app.setApplicationName("RORA")
    window = MainWindow(minimal=args.minimal)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

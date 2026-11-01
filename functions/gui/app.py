"""GUI entry point: `python -m functions.gui.app [--minimal] [--study FILE]` (scripts/run_pipeline.sh calls this)."""
import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_pipeline", description="RORA pipeline GUI")
    parser.add_argument("--minimal", action="store_true",
                        help="no debug checkpoints, no live viewport during compute, terminal-only log")
    parser.add_argument("--study", metavar="FILE",
                        help="user study mode: run the articulation trials listed in FILE (cfgs/study/example.yml)")
    args = parser.parse_args(argv)
    study = None
    if args.study:
        import yaml

        from functions.gui.study import load_study
        try:
            study = load_study(args.study)
        except (OSError, ValueError, yaml.YAMLError) as e:
            print(f"[error]: {e}")
            return 1
    try:
        from PySide6.QtWidgets import QApplication

        from functions.gui.window import MainWindow
    except ImportError as e:
        print(f"[error]: the GUI needs PySide6 and VTK's Qt support ({e}). Run: uv pip install -r requirements.txt")
        return 1
    app = QApplication(sys.argv[:1])
    app.setApplicationName("RORA")
    window = MainWindow(minimal=args.minimal, study=study)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

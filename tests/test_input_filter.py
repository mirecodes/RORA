import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget  # noqa: E402

from functions.gui.study import Recorder  # noqa: E402
from functions.gui.window import InputFilter  # noqa: E402

app = QApplication.instance() or QApplication([])


def _mouse(ts, kind=QEvent.Type.MouseButtonPress):
    e = QMouseEvent(kind, QPointF(1, 1), QPointF(1, 1), Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    e.setTimestamp(ts)
    return e


def _key(ts, repeat=False):
    e = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_W, Qt.KeyboardModifier.NoModifier, "w", repeat)
    e.setTimestamp(ts)
    return e


def test_input_filter_counts_each_event_once():
    rec = Recorder()
    rec.start()
    viewport, panel = QWidget(), QWidget()
    inside, label, done = QWidget(viewport), QLabel("hint", panel), QPushButton("Done ▸", panel)
    f = InputFilter(rec, viewport)
    press = _mouse(100)
    f.eventFilter(label, press)
    f.eventFilter(panel, press)                     # the ignored press re-sent to the parent: one click
    f.eventFilter(inside, _mouse(101))              # viewport presses are reported by the viewport
    f.eventFilter(done, _mouse(102))
    f.eventFilter(done, _mouse(103, QEvent.Type.MouseButtonDblClick))  # 2nd click of a double-click
    key = _key(104)
    f.eventFilter(inside, key)
    f.eventFilter(viewport, key)
    f.eventFilter(inside, _key(105, repeat=True))
    assert rec.counts == {"gui": 3, "axis": 0, "gizmo": 0, "view": 0, "key": 1}
    assert [e["detail"] for e in rec.events if e["kind"] == "gui"] == ["QLabel", "Done ▸", "Done ▸"]
    assert [e["repeat"] for e in rec.events if e["kind"] == "key"] == [False, True]


if __name__ == "__main__":
    test_input_filter_counts_each_event_once()
    print("ok")

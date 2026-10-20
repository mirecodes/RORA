import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from functions.gui.panel import InteractionHost, LogView, Timeline  # noqa: E402
from functions.gui.panel import ParamEditor  # noqa: E402
from functions.gui.params_io import load_comments  # noqa: E402
from functions.gui.runner import STAGE_ORDER  # noqa: E402
from functions.utils.config import load_object, load_params  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_timeline_flow():
    tl = Timeline()
    tl.reset({s: "pending" for s in STAGE_ORDER} | {"align": "cached"}, {s: True for s in STAGE_ORDER})
    assert tl.rows["align"].status == "cached"
    tl.set_status("refine", "running")
    assert tl.rows["refine"].expanded
    tl.add_plan("refine", [("cleaning", "① Cleaning", True), ("poisson", "② Poisson", False),
                           ("save", "Save", True)])
    tl.add_plan("refine", [("save", "Save", True), ("extra", "Extra", True)])  # appends unseen keys only
    assert list(tl.rows["refine"].subs) == ["cleaning", "poisson", "save", "extra"]
    assert tl.rows["refine"].subs["poisson"].state == "skipped"
    tl.set_step("refine", "cleaning", "running")
    assert tl.current_step("refine") == "cleaning"
    tl.set_step("refine", "cleaning", "done", "0.4s")
    tl.set_step("refine", "save", "running")
    tl.finish("refine", "done", 1.5, ("save", 1.1))
    row = tl.rows["refine"]
    assert row.status == "done" and not row.expanded
    assert row.subs["save"].state == "done"
    assert row.summary.text() == "2/3 · 1.5s"


def test_timeline_signals_and_busy():
    tl = Timeline()
    tl.reset({s: "done" for s in STAGE_ORDER}, {s: True for s in STAGE_ORDER})
    got = []
    tl.rerun.connect(lambda s: got.append(("rerun", s)))
    tl.toggled.connect(lambda s, on: got.append(("toggled", s, on)))
    tl.rows["segment"]._show_actions(True)  # hover state: actions are enabled only on hover
    tl.rows["segment"].rerun_btn.click()
    tl.rows["bind"].check.setChecked(False)
    assert got == [("rerun", "segment"), ("toggled", "bind", False)]
    tl.set_busy(True)
    assert not tl.rows["segment"].rerun_btn.isEnabled()


def test_interaction_host_and_log():
    host = InteractionHost()
    host.set_widget(QLabel("scene"))
    assert host.idle.isHidden()
    host.set_idle("Computing…")
    assert not host.idle.isHidden() and host.idle.text() == "Computing…"
    log = LogView()
    log.append("[info] one\n[info] two\n")
    assert log.last.text() == "[info] two"
    log.append("partial")
    assert log.last.text() == "partial"


def make_editor():
    editor = ParamEditor()
    editor.load(load_object(""), load_params(object_profile=""), load_comments(), ["toy_20261020_143012"])
    return editor


def test_editor_edits_values_and_marks_modified():
    editor = make_editor()
    changed = []
    editor.changed.connect(lambda: changed.append(1))
    box = editor.widgets[("params", "decompose", "coacd", "threshold")]
    box.setText("0.2")
    box.editingFinished.emit()
    obj, params = editor.values()
    assert params["decompose"]["coacd"]["threshold"] == 0.2 and changed and editor.modified()
    assert editor.sections["decompose"].modified
    editor.revert()
    assert not editor.modified()
    assert editor.values()[1]["decompose"]["coacd"]["threshold"] != 0.2


def test_editor_kinds_and_object_reload_signal():
    editor = make_editor()
    assert type(editor.widgets[("params", "refine", "method")]).__name__ == "QComboBox"
    assert type(editor.widgets[("params", "transform", "use_auto_alignment")]).__name__ == "QCheckBox"
    pct = editor.widgets[("params", "refine", "pymeshlab", "params", "meshing_isotropic_explicit_remeshing",
                          "targetlen")]
    pct.setText("abc")
    pct.editingFinished.emit()
    assert editor.values()[1]["refine"]["pymeshlab"]["params"]["meshing_isotropic_explicit_remeshing"][
        "targetlen"] == "1%"  # invalid text is rejected
    reloads = []
    editor.object_changed.connect(reloads.append)
    combo = editor.widgets[("obj", "object_profile")]
    combo.setCurrentIndex(combo.findText("toy_20261020_143012"))
    # deferred: the reload rebuilds the form, so it must not run inside the combo's own signal
    assert reloads == []
    app.processEvents()
    assert reloads and reloads[-1]["object_profile"] == "toy_20261020_143012"
    assert ("obj", "parts", "num") in editor.widgets  # parts.num lives in the Segment section
    editor.set_stage_enabled("bind", False)
    assert editor.values()[1]["pipeline"]["stages"]["bind"] is False


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")

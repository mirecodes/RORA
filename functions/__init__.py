try:
    # The GUI's Qt6 must load before pymeshlab's bundled Qt5 (imported by the stages below);
    # the other order segfaults on macOS when the QApplication starts.
    import PySide6.QtWidgets  # noqa: F401  (QtCore/QtGui alone are not enough)
except ImportError:  # headless install without the GUI
    pass

from .pipeline.transform import stage_transform, restore_transform
from .pipeline.refine import stage_refine
from .pipeline.decompose import stage_decompose
from .pipeline.segment import stage_segment
from .pipeline.articulate import stage_articulate
from .pipeline.bind import stage_bind

total_gui_time = 0.0
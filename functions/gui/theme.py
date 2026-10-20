"""Light/dark design tokens shared by the Qt widgets and the VTK viewport. Qt-free."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str          # window background
    panel: str       # side panel and header
    line: str        # borders, timeline rail
    text: str        # primary text
    text2: str       # secondary text
    text3: str       # muted text, section headers
    accent: str      # current step, selection, primary button
    ok: str          # done
    warn: str        # stale
    err: str         # failed
    button: str      # secondary button and input background
    vp_top: str      # viewport gradient (top)
    vp_bottom: str   # viewport gradient (bottom)
    mesh: str        # neutral mesh color
    revolute: str
    prismatic: str
    none: str        # unselected joint candidate, muted geometry
    axis_x: str
    axis_y: str
    axis_z: str
    hover: str       # gizmo / view cube hover highlight


DARK = Theme("dark", bg="#1b1d22", panel="#1f2127", line="#2c2f36", text="#e8eaee", text2="#b5bac3",
             text3="#7d838e", accent="#6aa9ff", ok="#5fb37e", warn="#e0a43a", err="#e06c6c", button="#2a2d34",
             vp_top="#2a2e36", vp_bottom="#1e2026", mesh="#8fb4d8", revolute="#F2B33D", prismatic="#4F8DF5",
             none="#8a8f98", axis_x="#e06c6c", axis_y="#6cc58a", axis_z="#6aa9ff", hover="#ffffff")
LIGHT = Theme("light", bg="#f4f5f7", panel="#ffffff", line="#e2e4e8", text="#1d2027", text2="#4a505b",
              text3="#8a909a", accent="#2f6fdc", ok="#2f9e5d", warn="#c98a1b", err="#cc4b4b", button="#f0f1f4",
              vp_top="#fbfbfc", vp_bottom="#e2e5ea", mesh="#7a9cc0", revolute="#D99A1E", prismatic="#2F6FDC",
              none="#a3a8b1", axis_x="#d0503f", axis_y="#3f9e5a", axis_z="#2f6fdc", hover="#000000")

_current = DARK


def current() -> Theme:
    return _current


def set_current(theme: Theme) -> None:
    global _current
    _current = theme


def rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def stylesheet(t: Theme) -> str:
    """Qt stylesheet for the whole app. Widgets pick rules through objectName and dynamic properties."""
    return f"""
QWidget {{ background: {t.panel}; color: {t.text2}; font-size: 12px; }}
QMainWindow {{ background: {t.bg}; }}
QWidget#Header {{ border-bottom: 1px solid {t.line}; }}
QWidget#Panel {{ border-left: 1px solid {t.line}; }}
QFrame#Divider {{ background: {t.line}; min-height: 1px; max-height: 1px; }}
QLabel#Title {{ color: {t.text}; font-weight: 600; font-size: 13px; }}
QLabel#Section {{ color: {t.text3}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
QLabel#Muted {{ color: {t.text3}; }}
QLabel#Meta {{ color: {t.text3}; font-family: Menlo, monospace; font-size: 10px; }}
QLabel#Modified {{ color: {t.accent}; }}
QPushButton {{ background: {t.button}; color: {t.text}; border: 1px solid {t.line}; border-radius: 5px; padding: 4px 10px; }}
QPushButton:hover {{ border-color: {t.accent}; }}
QPushButton:disabled {{ color: {t.text3}; }}
QPushButton:checked {{ border-color: {t.accent}; background: {t.bg}; }}
QPushButton[primary="true"] {{ background: {t.accent}; border-color: {t.accent}; color: #ffffff; }}
QToolButton {{ background: transparent; border: none; color: {t.text2}; padding: 2px 4px; }}
QToolButton:hover {{ color: {t.text}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {t.button}; color: {t.text}; border: 1px solid {t.line}; border-radius: 4px; padding: 2px 6px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t.accent}; }}
QPlainTextEdit {{ background: {t.bg}; color: {t.text2}; border: 1px solid {t.line}; font-family: Menlo, monospace; font-size: 11px; }}
QScrollArea {{ border: none; }}
QSplitter::handle {{ background: {t.line}; }}
QLabel#Dot {{ border: 2px solid {t.line}; border-radius: 6px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }}
QLabel#Dot[state="running"], QLabel#Dot[state="waiting"] {{ background: {t.accent}; border-color: {t.accent}; }}
QLabel#Dot[state="done"] {{ background: {t.ok}; border-color: {t.ok}; }}
QLabel#Dot[state="cached"] {{ background: {t.text3}; border-color: {t.text3}; }}
QLabel#Dot[state="stale"] {{ border-color: {t.warn}; }}
QLabel#Dot[state="failed"] {{ background: {t.err}; border-color: {t.err}; }}
QLabel#StageName {{ color: {t.text2}; }}
QLabel#StageName[state="pending"], QLabel#StageName[state="stopped"] {{ color: {t.text3}; }}
QLabel#StageName[state="running"], QLabel#StageName[state="waiting"] {{ color: {t.text}; font-weight: 600; }}
QWidget#SubSteps {{ border-left: 2px solid {t.line}; margin-left: 5px; }}
QLabel#SubDot {{ background: {t.line}; border-radius: 3px; min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px; }}
QLabel#SubDot[state="running"], QLabel#SubDot[state="waiting"] {{ background: {t.accent}; }}
QLabel#SubDot[state="done"] {{ background: {t.ok}; }}
QLabel#SubDot[state="failed"] {{ background: {t.err}; }}
QLabel#SubDot[state="skipped"] {{ background: transparent; border: 1px solid {t.line}; }}
QLabel#SubName {{ color: {t.text2}; font-size: 11px; }}
QLabel#SubName[state="pending"] {{ color: {t.text3}; }}
QLabel#SubName[state="skipped"] {{ color: {t.text3}; text-decoration: line-through; }}
QLabel#SubName[state="running"], QLabel#SubName[state="waiting"] {{ color: {t.text}; }}
"""

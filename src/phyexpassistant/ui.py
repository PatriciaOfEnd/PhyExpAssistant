from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path
import json
import random
import sys

from .llm_client import LLMClient, LLMError
from .experiments import (
    experiment_catalog_text,
    experiments_dir,
    get_experiment,
    list_experiments,
    normalize_experiment_catalog,
    normalize_generated_template_payload,
    normalize_template_payload,
    read_experiment_catalog,
    reload_experiment_catalog,
    validate_experiment_catalog,
    save_experiment_catalog,
)
from .paths import app_home, app_icon_path, resolve_input_path
from .settings import Settings, load_settings, save_settings
from .workflow import (
    B_UNCERTAINTY_METHODS,
    WorkflowError,
    generate_report,
)


@dataclass(frozen=True)
class ThemePalette:
    name: str
    background: str
    foreground: str
    surface: str
    surface_alt: str
    border: str
    accent: str
    accent_text: str
    button_bg: str
    button_hover: str
    input_bg: str
    input_border: str
    selection_bg: str
    muted: str
    scrollbar_bg: str
    scrollbar_handle: str
    scrollbar_handle_hover: str
    header_subtitle: str


THEME_PRESETS = {
    "light": {
        "name": "白色",
        "background": "#f5f7fb",
        "foreground": "#1f2937",
        "accent": "#5b7cfa",
    },
    "dark": {
        "name": "深色",
        "background": "#10151f",
        "foreground": "#e5e7eb",
        "accent": "#7aa2ff",
    },
    "mint": {
        "name": "薄荷",
        "background": "#f3fbf7",
        "foreground": "#24302a",
        "accent": "#3fa9a0",
    },
    "lavender": {
        "name": "薰衣草",
        "background": "#f6f4ff",
        "foreground": "#2c2740",
        "accent": "#7c6fe6",
    },
    "peach": {
        "name": "暖杏",
        "background": "#fff7ef",
        "foreground": "#3b2f27",
        "accent": "#d27f5e",
    },
}


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[index : index + 2], 16) for index in (0, 2, 4))


def _rgb_to_hex(color: tuple[int, int, int]) -> str:
    red, green, blue = color
    return f"#{red:02x}{green:02x}{blue:02x}"


def _mix_color(first: str, second: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    red1, green1, blue1 = _hex_to_rgb(first)
    red2, green2, blue2 = _hex_to_rgb(second)
    blended = (
        round(red1 * (1 - ratio) + red2 * ratio),
        round(green1 * (1 - ratio) + green2 * ratio),
        round(blue1 * (1 - ratio) + blue2 * ratio),
    )
    return _rgb_to_hex(blended)


def _relative_luminance(color: str) -> float:
    red, green, blue = [value / 255.0 for value in _hex_to_rgb(color)]

    def convert(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red = convert(red)
    green = convert(green)
    blue = convert(blue)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _build_custom_palette(background: str, foreground: str) -> ThemePalette:
    is_light_background = _relative_luminance(background) >= 0.5
    surface_mix = "#ffffff" if is_light_background else "#0f172a"
    surface = _mix_color(background, surface_mix, 0.10)
    surface_alt = _mix_color(background, surface_mix, 0.18)
    border = _mix_color(background, foreground, 0.18)
    button_bg = _mix_color(background, foreground, 0.08)
    button_hover = _mix_color(background, foreground, 0.16)
    input_bg = surface
    selection_bg = _mix_color(background, foreground, 0.22)
    muted = _mix_color(background, foreground, 0.45)
    scrollbar_bg = _mix_color(background, foreground, 0.06)
    scrollbar_handle = _mix_color(background, foreground, 0.24)
    scrollbar_handle_hover = _mix_color(background, foreground, 0.36)
    accent = foreground
    accent_text = "#ffffff" if _relative_luminance(accent) < 0.5 else "#111827"
    header_subtitle = _mix_color(background, foreground, 0.55)
    return ThemePalette(
        name="自定义",
        background=background,
        foreground=foreground,
        surface=surface,
        surface_alt=surface_alt,
        border=border,
        accent=accent,
        accent_text=accent_text,
        button_bg=button_bg,
        button_hover=button_hover,
        input_bg=input_bg,
        input_border=border,
        selection_bg=selection_bg,
        muted=muted,
        scrollbar_bg=scrollbar_bg,
        scrollbar_handle=scrollbar_handle,
        scrollbar_handle_hover=scrollbar_handle_hover,
        header_subtitle=header_subtitle,
    )


def build_theme_palette(settings: Settings) -> ThemePalette:
    if settings.ui_theme == "custom":
        return _build_custom_palette(settings.ui_custom_background, settings.ui_custom_foreground)

    preset = THEME_PRESETS.get(settings.ui_theme, THEME_PRESETS["light"])
    background = preset["background"]
    foreground = preset["foreground"]
    accent = preset["accent"]
    is_dark = _relative_luminance(background) < 0.5
    surface = _mix_color(background, "#ffffff" if not is_dark else "#111827", 0.06 if not is_dark else 0.18)
    surface_alt = _mix_color(background, "#ffffff" if not is_dark else "#111827", 0.11 if not is_dark else 0.24)
    border = _mix_color(background, foreground, 0.12 if not is_dark else 0.24)
    button_bg = _mix_color(background, foreground, 0.05 if not is_dark else 0.12)
    button_hover = _mix_color(background, foreground, 0.10 if not is_dark else 0.18)
    input_bg = surface
    input_border = border
    selection_bg = _mix_color(accent, background, 0.22)
    muted = _mix_color(background, foreground, 0.55 if not is_dark else 0.65)
    scrollbar_bg = _mix_color(background, foreground, 0.05 if not is_dark else 0.10)
    scrollbar_handle = _mix_color(background, foreground, 0.18 if not is_dark else 0.30)
    scrollbar_handle_hover = _mix_color(background, foreground, 0.28 if not is_dark else 0.42)
    accent_text = "#ffffff" if _relative_luminance(accent) < 0.5 else "#111827"
    header_subtitle = _mix_color(background, foreground, 0.52 if not is_dark else 0.66)
    return ThemePalette(
        name=preset["name"],
        background=background,
        foreground=foreground,
        surface=surface,
        surface_alt=surface_alt,
        border=border,
        accent=accent,
        accent_text=accent_text,
        button_bg=button_bg,
        button_hover=button_hover,
        input_bg=input_bg,
        input_border=input_border,
        selection_bg=selection_bg,
        muted=muted,
        scrollbar_bg=scrollbar_bg,
        scrollbar_handle=scrollbar_handle,
        scrollbar_handle_hover=scrollbar_handle_hover,
        header_subtitle=header_subtitle,
    )


def build_stylesheet(theme: ThemePalette, scale: float) -> str:
    font_size = _scaled(13, scale, minimum=11)
    title_size = _scaled(24, scale, minimum=18)
    subtitle_size = _scaled(13, scale, minimum=11)
    button_padding_v = _scaled(9, scale, minimum=6)
    button_padding_h = _scaled(14, scale, minimum=10)
    input_padding_v = _scaled(8, scale, minimum=6)
    input_padding_h = _scaled(10, scale, minimum=8)
    radius = _scaled(12, scale, minimum=8)
    group_radius = _scaled(14, scale, minimum=10)
    scrollbar_size = _scaled(10, scale, minimum=8)
    line_height = _scaled(36, scale, minimum=30)
    control_button_width = _scaled(34, scale, minimum=28)
    spin_button_height = max(14, line_height // 2)
    icon_paths = _ensure_ui_icon_paths(theme)
    return f"""
        QWidget {{
            background: {theme.background};
            color: {theme.foreground};
            font-size: {font_size}px;
        }}
        QScrollArea#leftScrollArea,
        QScrollArea#manualScrollArea,
        QScrollArea#ocrScrollArea,
        QScrollArea#templateScrollArea,
        QWidget#mainContent,
        QWidget#leftPanelContent,
        QWidget#manualScrollContent,
        QWidget#ocrScrollContent,
        QWidget#templateScrollContent,
        QWidget#manualFieldsContainer,
        QWidget#manualFooterContainer,
        QWidget#ocrFooterContainer {{
            background: {theme.background};
            border: none;
        }}
        QScrollArea#leftScrollArea,
        QScrollArea#ocrScrollArea,
        QScrollArea#templateScrollArea {{
            padding: 0px;
            margin: 0px;
        }}
        QScrollBar:vertical {{
            background: {theme.scrollbar_bg};
            width: {scrollbar_size}px;
            margin: 2px;
            border-radius: {scrollbar_size // 2}px;
        }}
        QScrollBar::handle:vertical {{
            background: {theme.scrollbar_handle};
            min-height: {max(24, line_height)}px;
            border-radius: {scrollbar_size // 2}px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {theme.scrollbar_handle_hover};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            background: {theme.scrollbar_bg};
            height: {scrollbar_size}px;
            margin: 2px;
            border-radius: {scrollbar_size // 2}px;
        }}
        QScrollBar::handle:horizontal {{
            background: {theme.scrollbar_handle};
            min-width: {max(24, line_height)}px;
            border-radius: {scrollbar_size // 2}px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {theme.scrollbar_handle_hover};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QFrame#headerCard, QGroupBox, QFrame#themeDialogCard {{
            background: {theme.surface};
            border: 1px solid {theme.border};
            border-radius: {group_radius}px;
        }}
        QGroupBox {{
            margin-top: 10px;
            padding: {button_padding_v + 4}px;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
            color: {theme.foreground};
        }}
        #headerTitle {{
            font-size: {title_size}px;
            font-weight: 700;
            color: {theme.foreground};
        }}
        #headerSubtitle {{
            color: {theme.header_subtitle};
            font-size: {subtitle_size}px;
        }}
        QLabel#statusLabel {{
            color: {theme.muted};
        }}
        QLabel#themeHint {{
            color: {theme.muted};
        }}
        QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
            background: {theme.input_bg};
            color: {theme.foreground};
            border: 1px solid {theme.input_border};
            border-radius: {radius}px;
            padding: {input_padding_v}px {input_padding_h}px;
            selection-background-color: {theme.selection_bg};
        }}
        QSpinBox, QComboBox {{
            min-height: {line_height}px;
            padding-right: {control_button_width + input_padding_h}px;
        }}
        QSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: {control_button_width}px;
            height: {spin_button_height}px;
            background: {theme.button_bg};
            border-left: 1px solid {theme.border};
            border-bottom: 1px solid {theme.border};
            border-top-right-radius: {radius - 1}px;
            margin: 1px 1px 0px 0px;
        }}
        QSpinBox::up-button:hover {{
            background: {theme.button_hover};
        }}
        QSpinBox::up-button:pressed {{
            background: {theme.surface_alt};
        }}
        QSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: {control_button_width}px;
            height: {spin_button_height}px;
            background: {theme.button_bg};
            border-left: 1px solid {theme.border};
            border-top: 1px solid {theme.border};
            border-bottom-right-radius: {radius - 1}px;
            margin: 0px 1px 1px 0px;
        }}
        QSpinBox::down-button:hover {{
            background: {theme.button_hover};
        }}
        QSpinBox::down-button:pressed {{
            background: {theme.surface_alt};
        }}
        QSpinBox::up-arrow {{
            image: url("{icon_paths['spin_up']}");
            width: {_scaled(12, scale, minimum=10)}px;
            height: {_scaled(12, scale, minimum=10)}px;
        }}
        QSpinBox::down-arrow {{
            image: url("{icon_paths['spin_down']}");
            width: {_scaled(12, scale, minimum=10)}px;
            height: {_scaled(12, scale, minimum=10)}px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: {control_button_width}px;
            background: {theme.button_bg};
            border-left: 1px solid {theme.border};
            border-top-right-radius: {radius - 1}px;
            border-bottom-right-radius: {radius - 1}px;
            margin: 1px 1px 1px 0px;
        }}
        QComboBox::drop-down:hover {{
            background: {theme.button_hover};
        }}
        QComboBox::drop-down:pressed {{
            background: {theme.surface_alt};
        }}
        QComboBox::down-arrow {{
            image: url("{icon_paths['combo_down']}");
            width: {_scaled(12, scale, minimum=10)}px;
            height: {_scaled(12, scale, minimum=10)}px;
        }}
        QComboBox QAbstractItemView {{
            background: {theme.surface};
            color: {theme.foreground};
            border: none;
            border-radius: 0px;
            padding: 0px;
            selection-background-color: {theme.selection_bg};
            selection-color: {theme.accent_text};
            outline: none;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: {line_height}px;
            padding: 0px {input_padding_h}px;
            border: none;
            background: {theme.surface};
        }}
        QComboBox QAbstractItemView::item:hover {{
            background: {theme.button_hover};
        }}
        QComboBox QAbstractItemView::item:selected {{
            background: {theme.selection_bg};
            color: {theme.accent_text};
        }}
        QPlainTextEdit {{
            min-height: {_scaled(180, scale, minimum=130)}px;
        }}
        QPlainTextEdit[compactTextEdit="true"] {{
            min-height: 0px;
        }}
        QFrame#dateField {{
            background: {theme.input_bg};
            border: 1px solid {theme.input_border};
            border-radius: {radius}px;
        }}
        QFrame#dateField QLineEdit {{
            background: transparent;
            border: none;
            padding: {input_padding_v}px {input_padding_h}px;
        }}
        QFrame#dateField QToolButton {{
            background: transparent;
            border: none;
            border-left: 1px solid {theme.border};
            color: {theme.muted};
            padding: {input_padding_v}px {input_padding_h}px;
            min-width: {_scaled(34, scale, minimum=28)}px;
        }}
        QPushButton, QToolButton {{
            background: {theme.button_bg};
            color: {theme.foreground};
            border: 1px solid {theme.border};
            border-radius: {radius}px;
            padding: {button_padding_v}px {button_padding_h}px;
        }}
        QPushButton:hover, QToolButton:hover {{
            background: {theme.button_hover};
        }}
        QPushButton:pressed, QToolButton:pressed {{
            background: {theme.surface_alt};
        }}
        QPushButton#primaryButton {{
            background: {theme.accent};
            color: {theme.accent_text};
            border: 1px solid {theme.accent};
            font-weight: 600;
        }}
        QPushButton#primaryButton:hover {{
            background: {_mix_color(theme.accent, theme.background, 0.10)};
        }}
        QPushButton#primaryButton:pressed {{
            background: {_mix_color(theme.accent, theme.background, 0.18)};
        }}
        QToolButton#themeButton {{
            background: {theme.button_bg};
            color: {theme.foreground};
            border: 1px solid {theme.border};
            border-radius: {radius}px;
            padding: {button_padding_v}px {button_padding_h}px;
            min-width: {_scaled(72, scale, minimum=64)}px;
        }}
        QToolButton#themeButton:hover {{
            background: {theme.button_hover};
        }}
        QTabWidget::pane {{
            border: 1px solid {theme.border};
            border-radius: {radius}px;
            background: {theme.surface};
        }}
        QTabBar::tab {{
            background: {theme.button_bg};
            color: {theme.foreground};
            padding: {button_padding_v}px {button_padding_h + 2}px;
            border-top-left-radius: {radius}px;
            border-top-right-radius: {radius}px;
            margin-right: 4px;
        }}
        QTabBar::tab:selected {{
            background: {theme.surface};
            color: {theme.foreground};
        }}
        QCalendarWidget QWidget {{
            background: {theme.surface};
        }}
        QCalendarWidget QToolButton {{
            background: {theme.button_bg};
            color: {theme.foreground};
            border: 1px solid {theme.border};
            border-radius: {radius}px;
            padding: {button_padding_v}px {button_padding_h}px;
        }}
        QCalendarWidget QAbstractItemView:enabled {{
            background: {theme.surface};
            color: {theme.foreground};
            selection-background-color: {theme.selection_bg};
            selection-color: {theme.accent_text};
            outline: none;
        }}
        QCalendarWidget QMenu {{
            background: {theme.surface};
            color: {theme.foreground};
        }}
        QDialog {{
            background: {theme.background};
            color: {theme.foreground};
        }}
    """


def _scaled(value: int, scale: float, *, minimum: int | None = None, maximum: int | None = None) -> int:
    scaled_value = round(value * scale)
    if minimum is not None:
        scaled_value = max(minimum, scaled_value)
    if maximum is not None:
        scaled_value = min(maximum, scaled_value)
    return scaled_value


def _ensure_ui_icon_paths(theme: ThemePalette) -> dict[str, str]:
    theme_key = hashlib.sha1(f"{theme.background}|{theme.foreground}|{theme.accent}".encode("utf-8")).hexdigest()[:12]
    icon_dir = app_home() / "ui_icons" / theme_key
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon_specs = {
        "spin_up": _svg_plus(theme.foreground),
        "spin_down": _svg_minus(theme.foreground),
        "combo_down": _svg_chevron_down(theme.foreground),
    }
    icon_paths: dict[str, str] = {}
    for name, svg in icon_specs.items():
        icon_path = icon_dir / f"{name}.svg"
        if not icon_path.exists() or icon_path.read_text(encoding="utf-8") != svg:
            icon_path.write_text(svg, encoding="utf-8")
        icon_paths[name] = icon_path.as_posix()
    return icon_paths


def _svg_plus(color: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">
  <path d="M12 5v14M5 12h14" stroke="{color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>'''


def _svg_minus(color: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">
  <path d="M5 12h14" stroke="{color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>'''


def _svg_chevron_down(color: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">
  <path d="M6 9l6 6 6-6" stroke="{color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>'''


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PatriciaOfEnd.PhyExpAssistant")
    except Exception:
        pass


def launch_ui(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtCore import QObject, QDate, QEvent, QThread, QTimer, Qt, QUrl, Signal, Slot
        from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon
        from PySide6.QtWidgets import (
            QApplication,
            QButtonGroup,
            QCalendarWidget,
            QCheckBox,
            QColorDialog,
            QComboBox,
            QDialog,
            QFileDialog,
            QFormLayout,
            QFrame,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QPlainTextEdit,
            QScrollArea,
            QSizePolicy,
            QSpinBox,
            QTabWidget,
            QTableWidget,
            QTableWidgetItem,
            QToolButton,
            QVBoxLayout,
            QWidget,
        )
    except ModuleNotFoundError as exc:
        print("PySide6 未安装，无法启动 UI。请先安装可选依赖：pip install '.[ui]' 或 pip install PySide6")
        return 2

    globals().update(
        {
            "QApplication": QApplication,
            "QButtonGroup": QButtonGroup,
            "QCalendarWidget": QCalendarWidget,
            "QCheckBox": QCheckBox,
            "QColorDialog": QColorDialog,
            "QComboBox": QComboBox,
            "QDialog": QDialog,
            "QFileDialog": QFileDialog,
            "QFormLayout": QFormLayout,
            "QFrame": QFrame,
            "QGridLayout": QGridLayout,
            "QGroupBox": QGroupBox,
            "QHBoxLayout": QHBoxLayout,
            "QLabel": QLabel,
            "QLineEdit": QLineEdit,
            "QMainWindow": QMainWindow,
            "QMessageBox": QMessageBox,
            "QPushButton": QPushButton,
            "QPlainTextEdit": QPlainTextEdit,
            "QScrollArea": QScrollArea,
            "QSizePolicy": QSizePolicy,
            "QSpinBox": QSpinBox,
            "QTabWidget": QTabWidget,
            "QTableWidget": QTableWidget,
            "QTableWidgetItem": QTableWidgetItem,
            "QToolButton": QToolButton,
            "QVBoxLayout": QVBoxLayout,
            "QWidget": QWidget,
            "QObject": QObject,
            "QDate": QDate,
            "QEvent": QEvent,
            "QThread": QThread,
            "QTimer": QTimer,
            "Qt": Qt,
            "QUrl": QUrl,
            "Signal": Signal,
            "Slot": Slot,
            "QColor": QColor,
            "QDesktopServices": QDesktopServices,
            "QFont": QFont,
            "QIcon": QIcon,
        }
    )

    class AsyncTaskWorker(QObject):
        finished = Signal(object)
        failed = Signal(object)

        def __init__(self, job: Callable[[], object]) -> None:
            super().__init__()
            self._job = job

        @Slot()
        def run(self) -> None:
            try:
                result = self._job()
            except Exception as exc:  # pragma: no cover - forwarded to UI
                self.failed.emit(exc)
            else:
                self.finished.emit(result)

    class ProcessingIndicator(QWidget):
        PROCESSING_WORDS = [
            "正在证明哥德巴赫猜想的逆命题...",
            "正在获得 flag ...",
            "正在穿过血脑屏障...",
            "正在对牛弹琴...",
            "正在玩 Apex Legends ...",
            "正在和大模型整夜交心...",
            "正在加入幻觉...",
            "正在引入注意力机制...",
            "@grok, is this true?",
            "少女祈祷中...",
            "交战，搜索，搞定就撤！",
            "正在泄露 Canary ...",
            "正在编写 SQLi 语句...",
            "正在手搓 Shellcode",
            "正在去除 UPX 壳...",
            "正在脱 VMProtect 壳...",
            "正在进行 Hash 碰撞...",
            "正在伪造 JSON Web Token...",
            "{{ 7*7 }}",
            "正在踏上命途...",
            "正在发送/求放过...",
            "正在泄露 fd 指针...",
            "正在 Double Free 你的实验报告...",
            "正在寻找最直接、最简洁、最不绕弯子的方法...",
            "正在殴打 LaTeX 公式使其自动渲染...",
            "正在除以 0 ...",
            "starwalkingDivisionError",
            "正在加入 Starfall Koi...",
            "正在看 CopperKoi 的 Blog ...",
            "正在看 LyCecilion 的 WriteUp ...",
            "正在看 starwalking 的女装照片...",
            "正在看 PatriciaOfEnd 的浏览记录...",
        ]
        SPINNER_FRAMES = ["◐", "◓", "◑", "◒"]

        def __init__(self, scale: float, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._scale = scale
            self._word_sequence = list(self.PROCESSING_WORDS)
            self._word_index = 0
            self._spinner_index = 0
            self._tick_index = 0
            self._timer = QTimer(self)
            self._timer.setInterval(120)
            self._timer.timeout.connect(self._advance)
            self.setObjectName("processingIndicator")
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(_scaled(6, scale, minimum=4))

            self.word_label = QLabel(self.PROCESSING_WORDS[0], self)
            self.word_label.setObjectName("processingWordLabel")
            self.word_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            self.word_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.word_label.setMinimumWidth(_scaled(168, scale, minimum=132))

            self.spinner_label = QLabel(self.SPINNER_FRAMES[0], self)
            self.spinner_label.setObjectName("processingSpinnerLabel")
            self.spinner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.spinner_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.spinner_label.setMinimumWidth(_scaled(18, scale, minimum=16))

            layout.addWidget(self.word_label, 0)
            layout.addWidget(self.spinner_label, 0)
            self.hide()

        def start(self, initial_word: str | None = None) -> None:
            self._shuffle_processing_words()
            self._spinner_index = 0
            self._tick_index = 0
            self.word_label.setText(self._word_sequence[self._word_index])
            self.spinner_label.setText(self.SPINNER_FRAMES[self._spinner_index])
            self.show()
            self._timer.start()

        def stop(self) -> None:
            self._timer.stop()
            self.hide()

        def _advance(self) -> None:
            self._spinner_index = (self._spinner_index + 1) % len(self.SPINNER_FRAMES)
            self.spinner_label.setText(self.SPINNER_FRAMES[self._spinner_index])
            self._tick_index = (self._tick_index + 1) % 12
            if self._tick_index == 0:
                self._word_index += 1
                if self._word_index >= len(self._word_sequence):
                    self._shuffle_processing_words(previous_word=self.word_label.text())
                self.word_label.setText(self._word_sequence[self._word_index])

        def _shuffle_processing_words(self, *, previous_word: str | None = None) -> None:
            self._word_sequence = list(self.PROCESSING_WORDS)
            random.shuffle(self._word_sequence)
            if previous_word and len(self._word_sequence) > 1 and self._word_sequence[0] == previous_word:
                self._word_sequence.append(self._word_sequence.pop(0))
            self._word_index = 0

    class FlatDatePicker(QWidget):
        def __init__(self, scale: float, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._scale = scale
            self._date = QDate.currentDate()

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self._frame = QFrame(self)
            self._frame.setObjectName("dateField")
            frame_layout = QHBoxLayout(self._frame)
            frame_layout.setContentsMargins(0, 0, 0, 0)
            frame_layout.setSpacing(0)

            self._line = QLineEdit(self._frame)
            self._line.setReadOnly(True)
            self._line.setFrame(False)
            self._line.setCursorPosition(0)
            self._line.installEventFilter(self)

            self._button = QToolButton(self._frame)
            self._button.setText("▾")
            self._button.clicked.connect(self._open_popup)

            frame_layout.addWidget(self._line, 1)
            frame_layout.addWidget(self._button, 0)
            layout.addWidget(self._frame)
            self.setDate(self._date)

        def date(self) -> QDate:
            return self._date

        def setDate(self, selected_date: QDate) -> None:
            if selected_date.isValid():
                self._date = selected_date
                self._line.setText(selected_date.toString("yyyy-MM-dd"))

        def eventFilter(self, watched: object, event: QEvent) -> bool:
            if watched is self._line and event.type() == QEvent.Type.MouseButtonPress:
                self._open_popup()
                return True
            return super().eventFilter(watched, event)

        def _open_popup(self) -> None:
            popup = QDialog(self, Qt.Popup | Qt.FramelessWindowHint)
            popup.setObjectName("datePopup")
            popup_layout = QVBoxLayout(popup)
            popup_layout.setContentsMargins(
                _scaled(10, self._scale, minimum=8),
                _scaled(10, self._scale, minimum=8),
                _scaled(10, self._scale, minimum=8),
                _scaled(10, self._scale, minimum=8),
            )
            popup_layout.setSpacing(_scaled(8, self._scale, minimum=6))

            chosen = {"date": self._date}
            calendar = QCalendarWidget(popup)
            calendar.setGridVisible(False)
            calendar.setSelectedDate(self._date)
            calendar.setMinimumSize(_scaled(300, self._scale, minimum=250), _scaled(230, self._scale, minimum=200))

            def accept_date(selected_date: QDate) -> None:
                chosen["date"] = selected_date
                popup.accept()

            calendar.clicked.connect(accept_date)
            popup_layout.addWidget(calendar)

            footer = QHBoxLayout()
            footer.addStretch(1)
            today_button = QPushButton("今天", popup)
            cancel_button = QPushButton("取消", popup)
            today_button.clicked.connect(lambda: accept_date(QDate.currentDate()))
            cancel_button.clicked.connect(popup.reject)
            footer.addWidget(today_button)
            footer.addWidget(cancel_button)
            popup_layout.addLayout(footer)

            popup.move(self.mapToGlobal(self.rect().bottomLeft()))
            if popup.exec() == QDialog.DialogCode.Accepted:
                self.setDate(chosen["date"])

    class MeasurementInputBlock(QGroupBox):
        MIN_CONTENT_WIDTH = 700

        def __init__(
            self,
            title: str,
            unit_options: list[str],
            values_placeholder: str,
            scale: float,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(title, parent)
            self._scale = scale
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.setMinimumWidth(_scaled(self.MIN_CONTENT_WIDTH, scale, minimum=700))

            layout = QVBoxLayout(self)
            layout.setSpacing(_scaled(10, scale, minimum=6))

            top_row = QHBoxLayout()
            top_row.setSpacing(_scaled(8, scale, minimum=6))
            self.unit_combo = QComboBox(self)
            self.unit_combo.addItems(unit_options)
            self.unit_combo.setMinimumWidth(_scaled(96, scale, minimum=76))
            self.values_input = QLineEdit(self)
            self.values_input.setPlaceholderText(values_placeholder)
            self.values_input.setMinimumWidth(_scaled(320, scale, minimum=260))
            top_row.addWidget(QLabel("单位", self))
            top_row.addWidget(self.unit_combo, 0)
            top_row.addWidget(self.values_input, 1)
            layout.addLayout(top_row)

            uncertainty_row = QHBoxLayout()
            uncertainty_row.setSpacing(_scaled(8, scale, minimum=6))
            self.b_checkbox = QCheckBox("计算 B 类不确定度", self)
            self.b_checkbox.toggled.connect(self._toggle_uncertainty_input)
            self.division_label = QLabel("分度值", self)
            self.division_input = QLineEdit(self)
            self.division_input.setPlaceholderText("仪器分度值")
            self.division_input.setMinimumWidth(_scaled(150, scale, minimum=120))
            self.division_unit_label = QLabel(self.unit_combo.currentText(), self)
            self.method_combo = QComboBox(self)
            self.method_combo.addItem(B_UNCERTAINTY_METHODS["half_division_uniform"]["label"], "half_division_uniform")
            self.method_combo.addItem(B_UNCERTAINTY_METHODS["division_uniform"]["label"], "division_uniform")
            self.method_combo.setMinimumWidth(_scaled(210, scale, minimum=180))
            self.unit_combo.currentTextChanged.connect(self.division_unit_label.setText)
            uncertainty_row.addWidget(self.b_checkbox, 0)
            uncertainty_row.addWidget(self.division_label, 0)
            uncertainty_row.addWidget(self.division_input, 0)
            uncertainty_row.addWidget(self.division_unit_label, 0)
            uncertainty_row.addWidget(self.method_combo, 0)
            uncertainty_row.addStretch(1)
            layout.addLayout(uncertainty_row)
            self._toggle_uncertainty_input(False)

        def values(self) -> list[float]:
            values = []
            for item in self.values_input.text().replace("，", ",").split(","):
                item = item.strip()
                if item:
                    values.append(float(item))
            return values

        def unit(self) -> str:
            return self.unit_combo.currentText()

        def uncertainty(self) -> dict | None:
            if not self.b_checkbox.isChecked():
                return None
            division_text = self.division_input.text().strip()
            if not division_text:
                raise ValueError(f"{self.title()} 已勾选 B 类不确定度，请填写仪器分度值。")
            division_value = float(division_text)
            if division_value <= 0:
                raise ValueError(f"{self.title()} 的仪器分度值必须大于 0。")
            return {
                "enabled": True,
                "division": division_value,
                "unit": self.unit(),
                "method": self.method_combo.currentData(),
            }

        def _toggle_uncertainty_input(self, checked: bool) -> None:
            self.division_label.setVisible(checked)
            self.division_input.setVisible(checked)
            self.division_unit_label.setVisible(checked)
            self.method_combo.setVisible(checked)
            self.adjustSize()
            self.updateGeometry()
            window = self.window()
            if window is not None and hasattr(window, "_apply_manual_layout_profile"):
                window._apply_manual_layout_profile(reset_scroll=False)

    class OcrUncertaintyControl(QWidget):
        def __init__(self, field_label: str, unit: str, scale: float, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._field_label = field_label
            self._scale = scale

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(_scaled(8, scale, minimum=6))

            self.b_checkbox = QCheckBox("计算 B 类不确定度", self)
            self.b_checkbox.toggled.connect(self._toggle_uncertainty_input)
            self.division_label = QLabel("分度值", self)
            self.division_input = QLineEdit(self)
            self.division_input.setPlaceholderText("仪器分度值")
            self.division_input.setMinimumWidth(_scaled(130, scale, minimum=110))
            self.division_unit_label = QLabel(unit, self)
            self.method_combo = QComboBox(self)
            self.method_combo.addItem(B_UNCERTAINTY_METHODS["half_division_uniform"]["label"], "half_division_uniform")
            self.method_combo.addItem(B_UNCERTAINTY_METHODS["division_uniform"]["label"], "division_uniform")
            self.method_combo.setMinimumWidth(_scaled(190, scale, minimum=160))

            layout.addWidget(self.b_checkbox, 0)
            layout.addWidget(self.division_label, 0)
            layout.addWidget(self.division_input, 0)
            layout.addWidget(self.division_unit_label, 0)
            layout.addWidget(self.method_combo, 0)
            layout.addStretch(1)
            self._toggle_uncertainty_input(False)

        def set_uncertainty(self, uncertainty: dict | None) -> None:
            uncertainty = uncertainty or {}
            enabled = bool(uncertainty.get("enabled"))
            self.b_checkbox.setChecked(enabled)
            self.division_input.setText(str(uncertainty.get("division") or ""))
            method = str(uncertainty.get("method") or "half_division_uniform")
            index = self.method_combo.findData(method)
            if index >= 0:
                self.method_combo.setCurrentIndex(index)
            self._toggle_uncertainty_input(enabled)

        def uncertainty(self) -> dict | None:
            if not self.b_checkbox.isChecked():
                return None
            division_text = self.division_input.text().strip()
            if not division_text:
                raise ValueError(f"{self._field_label} 已勾选 B 类不确定度，请填写仪器分度值。")
            division_value = float(division_text)
            if division_value <= 0:
                raise ValueError(f"{self._field_label} 的仪器分度值必须大于 0。")
            return {
                "enabled": True,
                "division": division_value,
                "unit": self.division_unit_label.text(),
                "method": self.method_combo.currentData(),
            }

        def _toggle_uncertainty_input(self, checked: bool) -> None:
            self.division_label.setVisible(checked)
            self.division_input.setVisible(checked)
            self.division_unit_label.setVisible(checked)
            self.method_combo.setVisible(checked)
            self.adjustSize()
            self.updateGeometry()
            window = self.window()
            if window is not None and hasattr(window, "_resize_ocr_table"):
                window._resize_ocr_table()

    class ThemeSettingsDialog(QDialog):
        def __init__(self, parent_window: "MainWindow") -> None:
            super().__init__(parent_window)
            self.parent_window = parent_window
            self._theme_buttons: dict[str, QToolButton] = {}
            self.setWindowTitle("界面设置")
            self.setMinimumWidth(parent_window._s(520, minimum=420))

            layout = QVBoxLayout(self)
            layout.setContentsMargins(parent_window._s(18), parent_window._s(18), parent_window._s(18), parent_window._s(18))
            layout.setSpacing(parent_window._s(14))

            title = QLabel("颜色方案")
            title.setObjectName("headerTitle")
            hint = QLabel("点击圆形色块即可切换。自定义模式可以选择背景色和前景色。")
            hint.setObjectName("themeHint")
            hint.setWordWrap(True)
            layout.addWidget(title)
            layout.addWidget(hint)

            palette_card = QFrame(self)
            palette_card.setObjectName("themeDialogCard")
            palette_layout = QGridLayout(palette_card)
            palette_layout.setContentsMargins(parent_window._s(14), parent_window._s(14), parent_window._s(14), parent_window._s(14))
            palette_layout.setHorizontalSpacing(parent_window._s(18))
            palette_layout.setVerticalSpacing(parent_window._s(12))
            layout.addWidget(palette_card)

            theme_keys = ["light", "dark", "mint", "lavender", "peach", "custom"]
            for index, theme_key in enumerate(theme_keys):
                swatch_widget = self._build_theme_swatch(theme_key)
                palette_layout.addWidget(swatch_widget, index // 3, index % 3)

            custom_card = QFrame(self)
            custom_card.setObjectName("themeDialogCard")
            custom_layout = QGridLayout(custom_card)
            custom_layout.setContentsMargins(parent_window._s(14), parent_window._s(14), parent_window._s(14), parent_window._s(14))
            custom_layout.setHorizontalSpacing(parent_window._s(12))
            custom_layout.setVerticalSpacing(parent_window._s(8))
            layout.addWidget(custom_card)

            self.custom_background_button = QToolButton(custom_card)
            self.custom_foreground_button = QToolButton(custom_card)
            chip_size = parent_window._s(44, minimum=34)
            self.custom_background_button.setFixedSize(chip_size, chip_size)
            self.custom_foreground_button.setFixedSize(chip_size, chip_size)
            self.custom_background_button.clicked.connect(lambda: self._pick_custom_color("background"))
            self.custom_foreground_button.clicked.connect(lambda: self._pick_custom_color("foreground"))
            self.custom_background_label = QLabel(custom_card)
            self.custom_foreground_label = QLabel(custom_card)
            custom_layout.addWidget(QLabel("背景色", custom_card), 0, 0)
            custom_layout.addWidget(self.custom_background_button, 0, 1)
            custom_layout.addWidget(self.custom_background_label, 0, 2)
            custom_layout.addWidget(QLabel("前景色", custom_card), 1, 0)
            custom_layout.addWidget(self.custom_foreground_button, 1, 1)
            custom_layout.addWidget(self.custom_foreground_label, 1, 2)

            footer = QHBoxLayout()
            footer.addStretch(1)
            close_button = QPushButton("关闭")
            close_button.clicked.connect(self.accept)
            footer.addWidget(close_button)
            layout.addLayout(footer)
            self._refresh_selection()

        def _build_theme_swatch(self, theme_key: str) -> QWidget:
            container = QWidget(self)
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(self.parent_window._s(6, minimum=4))
            button = QToolButton(container)
            button.setCheckable(True)
            button.setFixedSize(self.parent_window._s(44, minimum=34), self.parent_window._s(44, minimum=34))
            button.clicked.connect(lambda checked=False, key=theme_key: self._choose_theme(key))
            label = QLabel(self._theme_label(theme_key), container)
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(button, 0, Qt.AlignCenter)
            layout.addWidget(label, 0, Qt.AlignCenter)
            self._theme_buttons[theme_key] = button
            return container

        def _theme_label(self, theme_key: str) -> str:
            if theme_key == "custom":
                return "自定义"
            return THEME_PRESETS[theme_key]["name"]

        def _theme_color(self, theme_key: str) -> str:
            if theme_key == "custom":
                return self.parent_window.settings.ui_custom_background
            return THEME_PRESETS[theme_key]["background"]

        def _choose_theme(self, theme_key: str) -> None:
            self.parent_window._apply_theme_choice(theme_key)
            self._refresh_selection()

        def _pick_custom_color(self, color_role: str) -> None:
            settings = self.parent_window.settings
            current_color = settings.ui_custom_background if color_role == "background" else settings.ui_custom_foreground
            title = "选择背景色" if color_role == "background" else "选择前景色"
            color = QColorDialog.getColor(QColor(current_color), self, title)
            if not color.isValid():
                return
            background = color.name() if color_role == "background" else settings.ui_custom_background
            foreground = color.name() if color_role == "foreground" else settings.ui_custom_foreground
            self.parent_window._apply_theme_choice("custom", background, foreground)
            self._refresh_selection()

        def _refresh_selection(self) -> None:
            settings = self.parent_window.settings
            selected_theme = settings.ui_theme if settings.ui_theme in [*THEME_PRESETS.keys(), "custom"] else "light"
            for theme_key, button in self._theme_buttons.items():
                selected = theme_key == selected_theme
                button.setChecked(selected)
                button.setStyleSheet(self._swatch_style(self._theme_color(theme_key), selected))
            self.custom_background_button.setStyleSheet(self._swatch_style(settings.ui_custom_background, selected_theme == "custom"))
            self.custom_foreground_button.setStyleSheet(self._swatch_style(settings.ui_custom_foreground, selected_theme == "custom"))
            self.custom_background_label.setText(settings.ui_custom_background)
            self.custom_foreground_label.setText(settings.ui_custom_foreground)

        def _swatch_style(self, color: str, selected: bool) -> str:
            size = self.parent_window._s(44, minimum=34)
            radius = size // 2
            border_width = 3 if selected else 1
            border_color = self.parent_window._theme_palette.accent if selected else self.parent_window._theme_palette.border
            hover_color = self.parent_window._theme_palette.accent
            return f"""
                QToolButton {{
                    background: {color};
                    border: {border_width}px solid {border_color};
                    border-radius: {radius}px;
                    padding: 0px;
                }}
                QToolButton:hover {{
                    border: 2px solid {hover_color};
                }}
            """

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.settings = load_settings()
            self._busy_active = False
            self._active_task_thread: QThread | None = None
            self._active_task_worker: AsyncTaskWorker | None = None
            self._pending_task_success_callback: Callable[[object], None] | None = None
            self._pending_task_result: object | None = None
            self._pending_task_error: Exception | None = None
            app = QApplication.instance()
            self._ui_scale = self._compute_ui_scale(app)
            self._theme_palette = build_theme_palette(self.settings)
            self.setWindowTitle("PhyExpAssistant")
            self.setMinimumSize(self._s(760, minimum=620), self._s(520, minimum=430))
            self.resize(self._s(1600, minimum=820), self._s(900, minimum=560))
            self._build_ui(app)
            self._apply_theme()
            self._apply_settings_to_form()
            self._refresh_experiment_dependent_ui()
            self._set_status("就绪")

        def _compute_ui_scale(self, app: QApplication | None) -> float:
            if app is None or app.primaryScreen() is None:
                return 1.0
            geometry = app.primaryScreen().availableGeometry()
            scale = min(1.0, geometry.width() / 1440, geometry.height() / 900)
            return max(0.72, scale)

        def _s(self, value: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
            return _scaled(value, self._ui_scale, minimum=minimum, maximum=maximum)

        def _apply_theme(self) -> None:
            app = QApplication.instance()
            if app is not None:
                app.setStyleSheet(build_stylesheet(self._theme_palette, self._ui_scale))

        def _apply_theme_choice(
            self,
            theme_key: str,
            custom_background: str | None = None,
            custom_foreground: str | None = None,
        ) -> None:
            if hasattr(self, "base_url_input"):
                self.settings = self._collect_settings()
            if theme_key not in [*THEME_PRESETS.keys(), "custom"]:
                theme_key = "light"
            self.settings.ui_theme = theme_key
            if custom_background:
                self.settings.ui_custom_background = custom_background
            if custom_foreground:
                self.settings.ui_custom_foreground = custom_foreground
            self._theme_palette = build_theme_palette(self.settings)
            self._apply_theme()
            save_settings(self.settings)
            if hasattr(self, "status_label"):
                self._set_status(f"已切换颜色方案：{self._theme_palette.name}")

        def _open_theme_dialog(self) -> None:
            dialog = ThemeSettingsDialog(self)
            dialog.exec()

        def _build_ui(self, app: QApplication | None) -> None:
            if app is not None:
                app.setStyle("Fusion")
                app.setFont(QFont("Microsoft YaHei UI", self._s(10, minimum=8)))

            central = QWidget()
            central.setObjectName("mainContent")
            central.setMinimumSize(self._s(900, minimum=620), self._s(720, minimum=520))
            self.setCentralWidget(central)

            root_layout = QVBoxLayout(central)
            root_layout.setContentsMargins(self._s(16), self._s(16), self._s(16), self._s(16))
            root_layout.setSpacing(self._s(12, minimum=8))

            self.theme_button = QToolButton()
            self.theme_button.setObjectName("themeButton")
            self.theme_button.setText("设置")
            self.theme_button.clicked.connect(self._open_theme_dialog)
            self.processing_indicator = ProcessingIndicator(self._ui_scale)
            root_layout.addWidget(_build_header(self.theme_button, self.processing_indicator, self._ui_scale))

            content_layout = QHBoxLayout()
            content_layout.setSpacing(self._s(14, minimum=8))
            root_layout.addLayout(content_layout, 1)

            left_scroll_area = QScrollArea()
            left_scroll_area.setObjectName("leftScrollArea")
            left_scroll_area.setWidgetResizable(True)
            left_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            left_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            left_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            left_scroll_area.setFixedWidth(self._s(360, minimum=320))
            left_scroll_area.setMinimumHeight(self._s(300, minimum=240))
            left_scroll_area.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            self.left_scroll_area = left_scroll_area

            left_panel = QWidget()
            left_panel.setObjectName("leftPanelContent")
            left_panel.setMinimumWidth(self._s(336, minimum=300))
            left_scroll_area.setWidget(left_panel)

            left_column = QVBoxLayout(left_panel)
            left_column.setContentsMargins(0, 0, self._s(8, minimum=6), 0)
            left_column.setSpacing(self._s(14, minimum=8))
            content_layout.addWidget(left_scroll_area, 0)

            right_column = QVBoxLayout()
            right_column.setSpacing(self._s(14, minimum=8))
            content_layout.addLayout(right_column, 1)

            experiment_card = QGroupBox("实验选择")
            experiment_layout = QFormLayout(experiment_card)
            experiment_layout.setLabelAlignment(Qt.AlignRight)
            self.experiment_combo = QComboBox()
            self.experiment_combo.setToolTip("选择实验名称；程序内部会使用对应实验 ID 生成报告。")
            for experiment in list_experiments():
                self.experiment_combo.addItem(experiment["name"], experiment["id"])
            self.experiment_combo.currentIndexChanged.connect(self._refresh_experiment_dependent_ui)
            experiment_layout.addRow("实验名称", self.experiment_combo)
            left_column.addWidget(experiment_card)

            plot_force_card = QGroupBox("计算机绘图")
            plot_force_layout = QFormLayout(plot_force_card)
            plot_force_layout.setLabelAlignment(Qt.AlignRight)
            self.force_plot_checkbox = QCheckBox("是否强制生成计算机绘图代码")
            self.force_plot_count_input = QSpinBox()
            self.force_plot_count_input.setRange(1, 3)
            self.force_plot_count_input.setValue(1)
            self.force_plot_count_input.setSuffix(" 张")
            self.force_plot_count_input.setEnabled(False)
            self.force_plot_checkbox.toggled.connect(self.force_plot_count_input.setEnabled)
            plot_force_layout.addRow(self.force_plot_checkbox)
            plot_force_layout.addRow("强制生成的计算机绘图张数", self.force_plot_count_input)
            left_column.addWidget(plot_force_card)

            settings_card = QGroupBox("LLM 设置")
            settings_layout = QFormLayout(settings_card)
            settings_layout.setLabelAlignment(Qt.AlignRight)

            self.base_url_input = QLineEdit()
            self.base_url_input.setPlaceholderText("https://api.openai.com/v1")
            self.model_input = QLineEdit()
            self.model_input.setPlaceholderText("gpt-4o-mini")
            self.api_key_input = QLineEdit()
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.api_key_input.setPlaceholderText("手动输入 API Key")
            self.timeout_input = QSpinBox()
            self.timeout_input.setRange(10, 600)
            self.timeout_input.setSuffix(" 秒")

            settings_layout.addRow("Base URL", self.base_url_input)
            settings_layout.addRow("Model", self.model_input)
            settings_layout.addRow("API Key", self.api_key_input)
            settings_layout.addRow("Timeout", self.timeout_input)

            settings_buttons = QHBoxLayout()
            self.save_settings_button = QPushButton("保存设置")
            self.save_settings_button.setObjectName("primaryButton")
            self.save_settings_button.clicked.connect(self._save_settings)
            settings_buttons.addWidget(self.save_settings_button)
            settings_buttons.addStretch(1)
            settings_layout.addRow(settings_buttons)

            left_column.addWidget(settings_card)

            options_card = QGroupBox("输出选项")
            options_layout = QVBoxLayout(options_card)
            self.include_thinking_checkbox = QCheckBox("包含思考题")
            self.include_raw_appendix_checkbox = QCheckBox("包含原始数据附录")
            self.include_raw_appendix_checkbox.setChecked(True)
            self.use_llm_checkbox = QCheckBox("使用 LLM 生成报告文字")
            self.use_llm_checkbox.setChecked(True)
            options_layout.addWidget(self.include_thinking_checkbox)
            options_layout.addWidget(self.include_raw_appendix_checkbox)
            options_layout.addWidget(self.use_llm_checkbox)
            left_column.addWidget(options_card)

            quick_card = QGroupBox("快捷操作")
            quick_layout = QGridLayout(quick_card)
            self.open_output_button = QPushButton("打开输出目录")
            self.open_output_button.clicked.connect(self._open_output_dir)
            self.open_report_button = QPushButton("打开最近报告")
            self.open_report_button.clicked.connect(self._open_report)
            quick_layout.addWidget(self.open_output_button, 0, 0)
            quick_layout.addWidget(self.open_report_button, 0, 1)
            left_column.addWidget(quick_card)
            left_column.addStretch(1)

            self.tabs = QTabWidget()
            self.tabs.setMinimumWidth(self._s(680, minimum=560))
            right_column.addWidget(self.tabs, 1)

            self.tabs.addTab(self._build_manual_tab(), "手动录入")
            self.tabs.addTab(self._build_ocr_tab(), "手写识别")
            self.tabs.addTab(self._build_template_management_tab(), "模板管理")
            self._busy_widgets = [self.theme_button, self.left_scroll_area, self.tabs]

            footer = QFrame()
            footer_layout = QHBoxLayout(footer)
            footer_layout.setContentsMargins(0, 0, 0, 0)
            self.status_label = QLabel("")
            self.status_label.setObjectName("statusLabel")
            self.report_path_label = QLabel("最近报告：未生成")
            self.report_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            footer_layout.addWidget(self.status_label, 1)
            footer_layout.addWidget(self.report_path_label, 2)
            root_layout.addWidget(footer)

        def _build_manual_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(self._s(14, minimum=8))

            self.manual_scroll_area = QScrollArea(tab)
            self.manual_scroll_area.setObjectName("manualScrollArea")
            self.manual_scroll_area.setWidgetResizable(True)
            self.manual_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            self.manual_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.manual_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.manual_scroll_area.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.manual_scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            self.manual_scroll_content = QWidget()
            self.manual_scroll_content.setObjectName("manualScrollContent")
            self.manual_scroll_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            self.manual_scroll_layout = QVBoxLayout(self.manual_scroll_content)
            self.manual_scroll_layout.setContentsMargins(0, 0, 0, 0)
            self.manual_scroll_layout.setSpacing(self._s(14, minimum=8))
            self.manual_scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            self.manual_photo_card = QGroupBox("选择实验报告照片", self.manual_scroll_content)
            self.manual_photo_card.setObjectName("manualPhotoCard")
            self.manual_photo_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            photo_layout = QVBoxLayout(self.manual_photo_card)
            photo_layout.setContentsMargins(self._s(12, minimum=8), self._s(10, minimum=8), self._s(12, minimum=8), self._s(10, minimum=8))
            photo_layout.setSpacing(self._s(8, minimum=6))
            photo_row = QHBoxLayout()
            photo_row.setSpacing(self._s(8, minimum=6))
            self.manual_report_photo_input = QLineEdit(self.manual_photo_card)
            self.manual_report_photo_input.setPlaceholderText("选择本地实验报告照片路径")
            photo_browse_button = QPushButton("浏览", self.manual_photo_card)
            photo_browse_button.clicked.connect(
                lambda: self._pick_file(self.manual_report_photo_input, "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)")
            )
            photo_row.addWidget(self.manual_report_photo_input, 1)
            photo_row.addWidget(photo_browse_button, 0)
            photo_layout.addLayout(photo_row)
            photo_hint_label = QLabel("仅本地选择，不参与 LLM 处理。", self.manual_photo_card)
            photo_hint_label.setObjectName("themeHint")
            photo_hint_label.setWordWrap(True)
            photo_layout.addWidget(photo_hint_label)

            self.manual_student_card = QGroupBox("学生信息", self.manual_scroll_content)
            self.manual_student_card.setObjectName("manualStudentCard")
            self.manual_student_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            student_layout = QFormLayout(self.manual_student_card)
            student_layout.setLabelAlignment(Qt.AlignRight)

            self.student_name_input = QLineEdit(self.manual_student_card)
            self.student_id_input = QLineEdit(self.manual_student_card)
            self.class_name_input = QLineEdit(self.manual_student_card)
            self.date_input = FlatDatePicker(self._ui_scale, self.manual_student_card)
            self.date_input.setDate(QDate.currentDate())

            student_layout.addRow("姓名", self.student_name_input)
            student_layout.addRow("学号", self.student_id_input)
            student_layout.addRow("班级", self.class_name_input)
            student_layout.addRow("日期", self.date_input)

            self.manual_fields_container = QWidget(self.manual_scroll_content)
            self.manual_fields_container.setObjectName("manualFieldsContainer")
            self.manual_fields_layout = QVBoxLayout(self.manual_fields_container)
            self.manual_fields_layout.setContentsMargins(0, 0, 0, 0)
            self.manual_fields_layout.setSpacing(self._s(14, minimum=8))
            self.manual_fields_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.manual_fields_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            self.manual_input_blocks: dict[str, MeasurementInputBlock] = {}

            self.manual_footer_container = QWidget(tab)
            self.manual_footer_container.setObjectName("manualFooterContainer")
            self.manual_footer_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.manual_footer_layout = QVBoxLayout(self.manual_footer_container)
            self.manual_footer_layout.setContentsMargins(0, 0, 0, 0)
            self.manual_footer_layout.setSpacing(self._s(8, minimum=6))
            (
                self.manual_report_note_card,
                self.manual_report_note_checkbox,
                self.manual_report_note_input,
            ) = self._build_report_note_controls(self.manual_footer_container)
            self.manual_generate_button = QPushButton("生成手动录入报告")
            self.manual_generate_button.setObjectName("primaryButton")
            self.manual_generate_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.manual_generate_button.clicked.connect(self._generate_from_manual)
            self.manual_footer_layout.addWidget(self.manual_report_note_card)
            self.manual_footer_layout.addWidget(self.manual_generate_button)

            self.manual_scroll_layout.addWidget(self.manual_photo_card)
            self.manual_scroll_layout.addWidget(self.manual_student_card)
            self.manual_scroll_layout.addWidget(self.manual_fields_container)
            self.manual_scroll_area.setWidget(self.manual_scroll_content)

            layout.addWidget(self.manual_scroll_area, 1)
            layout.addWidget(self.manual_footer_container, 0)
            self._rebuild_manual_inputs()
            return tab

        def _build_ocr_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(self._s(14, minimum=8))

            self.ocr_scroll_area = QScrollArea(tab)
            self.ocr_scroll_area.setObjectName("ocrScrollArea")
            self.ocr_scroll_area.setWidgetResizable(True)
            self.ocr_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            self.ocr_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.ocr_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.ocr_scroll_area.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.ocr_scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            self.ocr_scroll_content = QWidget(self.ocr_scroll_area)
            self.ocr_scroll_content.setObjectName("ocrScrollContent")
            self.ocr_scroll_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            ocr_content_layout = QVBoxLayout(self.ocr_scroll_content)
            ocr_content_layout.setContentsMargins(0, 0, self._s(4, minimum=2), 0)
            ocr_content_layout.setSpacing(self._s(14, minimum=8))
            ocr_content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            note_card = QGroupBox("备注", self.ocr_scroll_content)
            note_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            note_layout = QVBoxLayout(note_card)
            self.ocr_note_input = QPlainTextEdit(note_card)
            self.ocr_note_input.setPlaceholderText("可填写给 LLM 的识别备注，例如：表格第一列是序号、某列单位为 cm、请优先按从左到右顺序读取。此内容只用于图片识别 prompt。")
            self.ocr_note_input.setMinimumHeight(self._s(90, minimum=72))
            note_layout.addWidget(self.ocr_note_input)

            image_card = QGroupBox("手写图片识别", self.ocr_scroll_content)
            image_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            image_layout = QHBoxLayout(image_card)
            self.image_path_input = QLineEdit(image_card)
            self.image_path_input.setPlaceholderText("选择手写数据图片")
            image_browse = QPushButton("浏览", image_card)
            image_browse.clicked.connect(lambda: self._pick_file(self.image_path_input, "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"))
            ocr_button = QPushButton("LLM 识别", image_card)
            ocr_button.clicked.connect(self._run_ocr)
            image_layout.addWidget(self.image_path_input, 1)
            image_layout.addWidget(image_browse)
            image_layout.addWidget(ocr_button)

            preview_card = QGroupBox("识别结果预览", self.ocr_scroll_content)
            preview_layout = QVBoxLayout(preview_card)
            preview_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.ocr_warning_label = QLabel("尚未识别。", preview_card)
            self.ocr_warning_label.setWordWrap(True)
            self.ocr_warning_label.setObjectName("themeHint")
            self.ocr_result_table = QTableWidget(0, 7, preview_card)
            self.ocr_result_table.setHorizontalHeaderLabels(["字段", "名称", "单位", "数值", "原始识别", "置信度", "B 类不确定度"])
            self.ocr_result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.ocr_result_table.setFixedHeight(self._s(220, minimum=180))
            self.ocr_result_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.ocr_result_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.ocr_result_table.setColumnWidth(6, self._s(520, minimum=420))
            self.ocr_uncertainty_controls: dict[str, OcrUncertaintyControl] = {}
            self.ocr_preview_card = preview_card
            preview_layout.addWidget(self.ocr_warning_label)
            preview_layout.addWidget(self.ocr_result_table)
            preview_card.setMinimumHeight(self._s(280, minimum=230))

            raw_card = QGroupBox("结构化识别草稿", self.ocr_scroll_content)
            raw_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            raw_layout = QVBoxLayout(raw_card)
            self.ocr_preview = QPlainTextEdit(raw_card)
            self.ocr_preview.setPlaceholderText("点击 LLM 识别后，这里会显示结构化识别草稿，用户可手动修正。")
            self.ocr_preview.setFixedHeight(self._s(260, minimum=200))
            raw_layout.addWidget(self.ocr_preview)

            self.ocr_footer_container = QWidget(tab)
            self.ocr_footer_container.setObjectName("ocrFooterContainer")
            self.ocr_footer_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            ocr_footer_layout = QVBoxLayout(self.ocr_footer_container)
            ocr_footer_layout.setContentsMargins(0, 0, 0, 0)
            ocr_footer_layout.setSpacing(self._s(8, minimum=6))

            ocr_generate = QPushButton("使用当前草稿生成报告", self.ocr_footer_container)
            ocr_generate.setObjectName("primaryButton")
            ocr_generate.clicked.connect(self._generate_from_ocr_preview)
            (
                self.ocr_report_note_card,
                self.ocr_report_note_checkbox,
                self.ocr_report_note_input,
            ) = self._build_report_note_controls(self.ocr_footer_container)

            ocr_content_layout.addWidget(note_card)
            ocr_content_layout.addWidget(image_card)
            ocr_content_layout.addWidget(preview_card)
            ocr_content_layout.addWidget(raw_card)
            self.ocr_scroll_area.setWidget(self.ocr_scroll_content)

            ocr_footer_layout.addWidget(self.ocr_report_note_card)
            ocr_footer_layout.addWidget(ocr_generate)

            layout.addWidget(self.ocr_scroll_area, 1)
            layout.addWidget(self.ocr_footer_container, 0)
            return tab

        def _build_template_management_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(self._s(14, minimum=8))

            self.template_scroll_area = QScrollArea(tab)
            self.template_scroll_area.setObjectName("templateScrollArea")
            self.template_scroll_area.setWidgetResizable(True)
            self.template_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            self.template_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.template_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.template_scroll_area.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.template_scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            self.template_scroll_content = QWidget(self.template_scroll_area)
            self.template_scroll_content.setObjectName("templateScrollContent")
            self.template_scroll_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            template_layout = QVBoxLayout(self.template_scroll_content)
            template_layout.setContentsMargins(0, 0, self._s(4, minimum=2), 0)
            template_layout.setSpacing(self._s(14, minimum=8))
            template_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            def compact_editor(parent: QWidget, placeholder: str, height: int, *, minimum: int, no_wrap: bool = False) -> QPlainTextEdit:
                editor = QPlainTextEdit(parent)
                editor.setProperty("compactTextEdit", True)
                editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                editor.setPlaceholderText(placeholder)
                if no_wrap:
                    editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
                editor.setFixedHeight(self._s(height, minimum=minimum))
                return editor

            catalog_card = QGroupBox("管理现有模板（多文件合并视图）", self.template_scroll_content)
            catalog_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            catalog_layout = QVBoxLayout(catalog_card)
            catalog_hint = QLabel(f"当前模板目录：{experiments_dir()}；编辑器显示合并视图，保存时会按实验 id 写回多个 .json 文件。", catalog_card)
            catalog_hint.setObjectName("themeHint")
            catalog_hint.setWordWrap(True)
            self.template_catalog_editor = compact_editor(
                catalog_card,
                "这里是所有实验模板的合并视图；可直接编辑后保存为多个模板文件。",
                360,
                minimum=280,
                no_wrap=True,
            )
            catalog_buttons = QHBoxLayout()
            reload_button = QPushButton("重新载入", catalog_card)
            reload_button.clicked.connect(self._load_template_catalog_editor)
            validate_button = QPushButton("验证 JSON", catalog_card)
            validate_button.clicked.connect(self._validate_template_catalog_editor)
            format_button = QPushButton("格式化", catalog_card)
            format_button.clicked.connect(self._format_template_catalog_editor)
            save_button = QPushButton("保存到模板目录", catalog_card)
            save_button.setObjectName("primaryButton")
            save_button.clicked.connect(self._save_template_catalog_editor)
            catalog_buttons.addWidget(reload_button)
            catalog_buttons.addWidget(validate_button)
            catalog_buttons.addWidget(format_button)
            catalog_buttons.addStretch(1)
            catalog_buttons.addWidget(save_button)
            catalog_layout.addWidget(catalog_hint)
            catalog_layout.addWidget(self.template_catalog_editor)
            catalog_layout.addLayout(catalog_buttons)

            paste_card = QGroupBox("直接粘贴导入模板", self.template_scroll_content)
            paste_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            paste_layout = QVBoxLayout(paste_card)
            paste_hint = QLabel("可粘贴完整模板目录合并 JSON、单个实验模板对象，或 {\"experiment\": {...}}。导入后会先校验，再合并到上方编辑器。", paste_card)
            paste_hint.setObjectName("themeHint")
            paste_hint.setWordWrap(True)
            self.template_paste_input = compact_editor(paste_card, "在这里粘贴模板 JSON。", 180, minimum=130, no_wrap=True)
            paste_buttons = QHBoxLayout()
            paste_import_button = QPushButton("导入到编辑器", paste_card)
            paste_import_button.setObjectName("primaryButton")
            paste_import_button.clicked.connect(self._import_template_from_paste)
            paste_clear_button = QPushButton("清空", paste_card)
            paste_clear_button.clicked.connect(self.template_paste_input.clear)
            paste_buttons.addStretch(1)
            paste_buttons.addWidget(paste_clear_button)
            paste_buttons.addWidget(paste_import_button)
            paste_layout.addWidget(paste_hint)
            paste_layout.addWidget(self.template_paste_input)
            paste_layout.addLayout(paste_buttons)

            file_card = QGroupBox("从 JSON 文件导入模板", self.template_scroll_content)
            file_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            file_layout = QVBoxLayout(file_card)
            file_row = QHBoxLayout()
            self.template_file_input = QLineEdit(file_card)
            self.template_file_input.setPlaceholderText("选择模板 JSON 文件")
            file_browse_button = QPushButton("浏览", file_card)
            file_browse_button.clicked.connect(lambda: self._pick_file(self.template_file_input, "JSON 文件 (*.json)"))
            file_import_button = QPushButton("导入到编辑器", file_card)
            file_import_button.setObjectName("primaryButton")
            file_import_button.clicked.connect(self._import_template_from_file)
            file_row.addWidget(self.template_file_input, 1)
            file_row.addWidget(file_browse_button)
            file_row.addWidget(file_import_button)
            file_layout.addLayout(file_row)

            ocr_card = QGroupBox("使用 Agent OCR 功能新建模板", self.template_scroll_content)
            ocr_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            ocr_layout = QVBoxLayout(ocr_card)
            ocr_hint = QLabel("选择多张包含实验公式、空白表格或实验报告格式的图片。若图片含已有数据，模型会被要求忽略具体数值，只抽象字段和公式。", ocr_card)
            ocr_hint.setObjectName("themeHint")
            ocr_hint.setWordWrap(True)
            self.template_ocr_images_input = compact_editor(ocr_card, "每行一个图片路径；也可以点击“选择图片”多选。", 110, minimum=82)
            self.template_ocr_note_input = compact_editor(ocr_card, "可选：填写实验名称、教材章节、希望使用的模板 ID、字段命名偏好等。", 96, minimum=74)
            ocr_buttons = QHBoxLayout()
            ocr_browse_button = QPushButton("选择图片", ocr_card)
            ocr_browse_button.clicked.connect(self._pick_template_ocr_images)
            ocr_generate_button = QPushButton("LLM OCR 生成模板", ocr_card)
            ocr_generate_button.setObjectName("primaryButton")
            ocr_generate_button.clicked.connect(self._run_template_ocr)
            ocr_buttons.addWidget(ocr_browse_button)
            ocr_buttons.addStretch(1)
            ocr_buttons.addWidget(ocr_generate_button)
            ocr_layout.addWidget(ocr_hint)
            ocr_layout.addWidget(QLabel("实验图片", ocr_card))
            ocr_layout.addWidget(self.template_ocr_images_input)
            ocr_layout.addWidget(QLabel("OCR 备注", ocr_card))
            ocr_layout.addWidget(self.template_ocr_note_input)
            ocr_layout.addLayout(ocr_buttons)

            report_card = QGroupBox("使用实验报告新建模板", self.template_scroll_content)
            report_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            report_layout = QVBoxLayout(report_card)
            report_hint = QLabel(
                "导入 .pdf / .docx / .docm / .doc 实验报告文件。程序会先本地提取可读文本，再交给 LLM 抽象模板；如果是纯图片扫描件，提取可能不完整。",
                report_card,
            )
            report_hint.setObjectName("themeHint")
            report_hint.setWordWrap(True)
            file_row = QHBoxLayout()
            self.template_report_input = QLineEdit(report_card)
            self.template_report_input.setPlaceholderText("选择实验报告文件")
            report_browse_button = QPushButton("浏览", report_card)
            report_browse_button.clicked.connect(lambda: self._pick_file(self.template_report_input, "实验报告文件 (*.pdf *.docx *.docm *.doc)"))
            report_generate_button = QPushButton("LLM 读取报告生成模板", report_card)
            report_generate_button.setObjectName("primaryButton")
            report_generate_button.clicked.connect(self._run_template_report_ocr)
            file_row.addWidget(self.template_report_input, 1)
            file_row.addWidget(report_browse_button)
            report_action_row = QHBoxLayout()
            report_action_row.addStretch(1)
            report_action_row.addWidget(report_generate_button)
            self.template_report_note_input = compact_editor(report_card, "可选：填写实验名称、章节、希望保留的模板 ID、字段命名偏好等。", 96, minimum=74)
            report_layout.addWidget(report_hint)
            report_layout.addLayout(file_row)
            report_layout.addWidget(QLabel("报告备注", report_card))
            report_layout.addWidget(self.template_report_note_input)
            report_layout.addLayout(report_action_row)

            self.template_status_label = QLabel("", self.template_scroll_content)
            self.template_status_label.setObjectName("themeHint")
            self.template_status_label.setWordWrap(True)

            template_layout.addWidget(catalog_card)
            template_layout.addWidget(paste_card)
            template_layout.addWidget(file_card)
            template_layout.addWidget(ocr_card)
            template_layout.addWidget(report_card)
            template_layout.addWidget(self.template_status_label)

            self.template_scroll_area.setWidget(self.template_scroll_content)
            layout.addWidget(self.template_scroll_area, 1)
            self._load_template_catalog_editor()
            return tab

        def _build_report_note_controls(self, parent: QWidget) -> tuple[QGroupBox, QCheckBox, QPlainTextEdit]:
            note_card = QGroupBox("报告生成备注", parent)
            note_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            note_layout = QVBoxLayout(note_card)
            note_layout.setContentsMargins(
                self._s(12, minimum=8),
                self._s(10, minimum=8),
                self._s(12, minimum=8),
                self._s(10, minimum=8),
            )
            note_layout.setSpacing(self._s(8, minimum=6))
            note_checkbox = QCheckBox("启用报告生成备注", note_card)
            note_input = QPlainTextEdit(note_card)
            note_input.setPlaceholderText(
                "可填写给 LLM 的报告生成备注，例如：强调有效数字、按指定顺序写误差分析、结果总结更简洁。此内容只用于报告生成 prompt。"
            )
            note_input.setMinimumHeight(self._s(90, minimum=72))
            note_layout.addWidget(note_checkbox)
            note_layout.addWidget(note_input)

            def set_note_enabled(checked: bool) -> None:
                note_input.setVisible(checked)
                note_input.setEnabled(checked)
                note_card.adjustSize()
                note_card.updateGeometry()

            note_checkbox.toggled.connect(set_note_enabled)
            set_note_enabled(False)
            return note_card, note_checkbox, note_input

        def _apply_settings_to_form(self) -> None:
            self.base_url_input.setText(self.settings.base_url)
            self.model_input.setText(self.settings.model)
            self.api_key_input.setText(self.settings.api_key)
            self.timeout_input.setValue(self.settings.timeout_seconds)

        def _collect_settings(self) -> Settings:
            settings = Settings(
                base_url=self.base_url_input.text().strip() or "https://api.openai.com/v1",
                api_key=self.api_key_input.text().strip(),
                model=self.model_input.text().strip() or "gpt-4o-mini",
                temperature=self.settings.temperature,
                timeout_seconds=self.timeout_input.value(),
                ui_theme=self.settings.ui_theme,
                ui_custom_background=self.settings.ui_custom_background,
                ui_custom_foreground=self.settings.ui_custom_foreground,
            )
            return settings

        def _save_settings(self) -> None:
            self.settings = self._collect_settings()
            save_settings(self.settings)
            self._set_status("设置已保存")
            QMessageBox.information(self, "保存成功", "LLM 设置已保存到本地。")

        def _pick_file(self, target: QLineEdit, filter_text: str) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件", str(Path.cwd()), filter_text)
            if path:
                target.setText(path)

        def _pick_template_ocr_images(self) -> None:
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "选择实验模板图片",
                str(Path.cwd()),
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)",
            )
            if paths:
                self.template_ocr_images_input.setPlainText("\n".join(paths))

        def _template_report_document_path(self) -> Path:
            file_path_text = self.template_report_input.text().strip()
            if not file_path_text:
                raise ValueError("请先选择实验报告文件。")
            file_path = resolve_input_path(file_path_text)
            if not file_path.is_file():
                raise ValueError(f"实验报告文件不存在或不是文件：{file_path}")
            if file_path.suffix.lower() not in {".pdf", ".docx", ".docm", ".doc"}:
                raise ValueError("仅支持 .pdf、.docx、.docm 和 .doc 实验报告文件。")
            return file_path

        def _load_template_catalog_editor(self) -> None:
            catalog = read_experiment_catalog()
            validate_experiment_catalog(catalog)
            self.template_catalog_editor.setPlainText(experiment_catalog_text(catalog))
            self._set_template_status(f"已载入 {len(catalog.get('experiments') or [])} 个模板。")

        def _template_catalog_from_editor(self) -> dict:
            text = self.template_catalog_editor.toPlainText().strip()
            if not text:
                raise ValueError("模板编辑器为空。")
            catalog = normalize_experiment_catalog(json.loads(text))
            return catalog

        def _set_template_catalog_editor(self, catalog: dict, message: str) -> None:
            normalized_catalog = normalize_experiment_catalog(catalog)
            self.template_catalog_editor.setPlainText(experiment_catalog_text(normalized_catalog))
            self._set_template_status(message)

        def _set_template_status(self, message: str) -> None:
            if hasattr(self, "template_status_label"):
                self.template_status_label.setText(message)
            if hasattr(self, "status_label"):
                self._set_status(message)

        def _validate_template_catalog_editor(self) -> None:
            try:
                catalog = self._template_catalog_from_editor()
                self._set_template_status(f"模板 JSON 校验通过，共 {len(catalog.get('experiments') or [])} 个模板。")
            except Exception as exc:
                self._show_error(exc)

        def _format_template_catalog_editor(self) -> None:
            try:
                catalog = self._template_catalog_from_editor()
                self._set_template_catalog_editor(catalog, "模板 JSON 已格式化。")
            except Exception as exc:
                self._show_error(exc)

        def _save_template_catalog_editor(self) -> None:
            try:
                catalog = self._template_catalog_from_editor()
                save_experiment_catalog(catalog)
                reload_experiment_catalog()
                self._refresh_experiment_combo()
                self._set_template_catalog_editor(catalog, f"模板目录已保存：{experiments_dir()}")
                QMessageBox.information(self, "保存成功", "模板目录已保存，并已刷新实验列表。")
            except Exception as exc:
                self._show_error(exc)

        def _import_template_from_paste(self) -> None:
            try:
                text = self.template_paste_input.toPlainText().strip()
                if not text:
                    raise ValueError("请先粘贴模板 JSON。")
                self._import_template_text_to_editor(text, source="粘贴内容")
            except Exception as exc:
                self._show_error(exc)

        def _import_template_from_file(self) -> None:
            try:
                file_path_text = self.template_file_input.text().strip()
                if not file_path_text:
                    raise ValueError("请先选择模板 JSON 文件。")
                file_path = resolve_input_path(file_path_text)
                if not file_path.is_file():
                    raise ValueError(f"模板 JSON 文件不存在或不是文件：{file_path}")
                self._import_template_text_to_editor(file_path.read_text(encoding="utf-8"), source=str(file_path))
            except Exception as exc:
                self._show_error(exc)

        def _import_template_text_to_editor(self, text: str, *, source: str) -> None:
            payload = json.loads(text)
            base_catalog = self._template_catalog_from_editor()
            catalog = normalize_template_payload(payload, base_catalog=base_catalog)
            self._set_template_catalog_editor(catalog, f"已从 {source} 导入模板草稿；请检查后保存。")

        def _template_ocr_image_paths(self) -> list[Path]:
            raw_paths = [line.strip() for line in self.template_ocr_images_input.toPlainText().splitlines() if line.strip()]
            if not raw_paths:
                raise ValueError("请至少选择一张模板图片。")
            image_paths = []
            for raw_path in raw_paths:
                image_path = resolve_input_path(raw_path)
                if not image_path.is_file():
                    raise ValueError(f"模板图片不存在或不是文件：{image_path}")
                image_paths.append(image_path)
            return image_paths

        def _run_template_ocr(self) -> None:
            try:
                settings = self._collect_settings()
                if not settings.is_llm_ready:
                    raise LLMError("请先填写 Base URL、Model 和 API Key。")
                image_paths = self._template_ocr_image_paths()
                note = self.template_ocr_note_input.toPlainText().strip()
                current_catalog = self._template_catalog_from_editor()

                def job() -> dict:
                    return LLMClient(settings).generate_experiment_template(image_paths, current_catalog, note=note)

                def handle_success(result: object) -> None:
                    if not isinstance(result, dict):
                        raise TypeError(f"模板 OCR 返回结果格式不正确：{type(result)!r}")
                    catalog = normalize_generated_template_payload(result, base_catalog=current_catalog)
                    self._set_template_catalog_editor(catalog, "LLM OCR 已生成并校验模板草稿；请检查后保存。")

                self._begin_background_task(
                    "正在通过 LLM OCR 生成模板...",
                    processing_word="Thinking",
                    job=job,
                    on_success=handle_success,
                )
            except Exception as exc:
                self._show_error(exc)

        def _run_template_report_ocr(self) -> None:
            try:
                settings = self._collect_settings()
                if not settings.is_llm_ready:
                    raise LLMError("请先填写 Base URL、Model 和 API Key。")
                document_path = self._template_report_document_path()
                note = self.template_report_note_input.toPlainText().strip()
                current_catalog = self._template_catalog_from_editor()

                def job() -> dict:
                    return LLMClient(settings).generate_experiment_template_from_report(document_path, current_catalog, note=note)

                def handle_success(result: object) -> None:
                    if not isinstance(result, dict):
                        raise TypeError(f"实验报告模板 OCR 返回结果格式不正确：{type(result)!r}")
                    catalog = normalize_generated_template_payload(result, base_catalog=current_catalog)
                    self._set_template_catalog_editor(catalog, "实验报告模板已生成并校验；请检查后保存。")

                self._begin_background_task(
                    "正在通过实验报告生成模板...",
                    processing_word="Thinking",
                    job=job,
                    on_success=handle_success,
                )
            except Exception as exc:
                self._show_error(exc)

        def _refresh_experiment_combo(self) -> None:
            if not hasattr(self, "experiment_combo"):
                return
            current_id = self.experiment_combo.currentData()
            experiments = list_experiments()
            self.experiment_combo.blockSignals(True)
            self.experiment_combo.clear()
            for experiment in experiments:
                self.experiment_combo.addItem(experiment["name"], experiment["id"])
            selected_index = self.experiment_combo.findData(current_id)
            self.experiment_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
            self.experiment_combo.blockSignals(False)
            self._refresh_experiment_dependent_ui()

        def _open_output_dir(self) -> None:
            from .paths import output_root

            output_dir = output_root()
            output_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_dir)))

        def _open_report(self) -> None:
            report_path = getattr(self, "_latest_report_path", None)
            if not report_path:
                QMessageBox.information(self, "提示", "还没有生成报告。")
                return
            path = Path(report_path)
            if path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            else:
                QMessageBox.warning(self, "提示", f"报告不存在：{path}")

        def _begin_background_task(
            self,
            task_message: str,
            *,
            processing_word: str,
            job: Callable[[], object],
            on_success: Callable[[object], None],
        ) -> None:
            if self._active_task_thread is not None:
                raise RuntimeError("当前已有任务正在运行，请稍候。")

            self._set_busy(True, task_message, processing_word=processing_word)
            thread = QThread(self)
            worker = AsyncTaskWorker(job)
            worker.moveToThread(thread)

            self._pending_task_success_callback = on_success

            worker.finished.connect(self._store_background_task_success)
            worker.failed.connect(self._store_background_task_failure)
            worker.finished.connect(thread.quit)
            worker.failed.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            worker.failed.connect(worker.deleteLater)
            thread.finished.connect(self._process_background_task_completion)
            thread.finished.connect(thread.deleteLater)
            thread.started.connect(worker.run)

            self._active_task_thread = thread
            self._active_task_worker = worker
            thread.start()

        def _clear_background_task(self) -> None:
            self._active_task_thread = None
            self._active_task_worker = None
            self._pending_task_success_callback = None
            self._pending_task_result = None
            self._pending_task_error = None
            self._set_busy(False, "")

        def _store_background_task_success(self, result: object) -> None:
            self._pending_task_result = result

        def _store_background_task_failure(self, exc: object) -> None:
            self._pending_task_error = exc if isinstance(exc, Exception) else RuntimeError(str(exc))

        @Slot()
        def _process_background_task_completion(self) -> None:
            callback = self._pending_task_success_callback
            result = self._pending_task_result
            error = self._pending_task_error
            self._active_task_thread = None
            self._active_task_worker = None
            self._pending_task_success_callback = None
            self._pending_task_result = None
            self._pending_task_error = None
            self._set_busy(False, "")
            try:
                if error is not None:
                    self._show_error(error)
                    return
                if callback is not None:
                    callback(result)
            except Exception as exc:  # pragma: no cover - forwarded to UI
                self._show_error(exc)

        def _generate_from_manual(self) -> None:
            try:
                data = {}
                for field_name, block in self.manual_input_blocks.items():
                    field_data = {"unit": block.unit(), "values": block.values()}
                    uncertainty = block.uncertainty()
                    if uncertainty:
                        field_data["b_uncertainty"] = uncertainty
                    data[field_name] = field_data
                request = {
                    "experiment_id": self._selected_experiment_id(),
                    "student": self._current_student(),
                    "options": self._current_options(),
                    "data": data,
                    "source": "manual",
                }
                photo_path = self.manual_report_photo_input.text().strip()
                if photo_path:
                    request["original_photo_path"] = photo_path
                report_note = self._report_generation_note("manual")
                if report_note:
                    request["report_generation_note"] = report_note
                self._run_generation(request)
            except Exception as exc:
                self._show_error(exc)

        def _run_ocr(self) -> None:
            try:
                settings = self._collect_settings()
                if not settings.is_llm_ready:
                    raise LLMError("请先填写 Base URL、Model 和 API Key。")
                image_path_text = self.image_path_input.text().strip()
                if not image_path_text:
                    raise ValueError("请先选择手写图片。")
                image_path = resolve_input_path(image_path_text)
                if not image_path.is_file():
                    raise ValueError(f"手写图片不存在或不是文件：{image_path}")
                note = self.ocr_note_input.toPlainText().strip() if hasattr(self, "ocr_note_input") else ""
                experiment_id = self._selected_experiment_id()

                def job() -> dict:
                    return LLMClient(settings).extract_handwritten_data(image_path, experiment_id, note=note)

                def handle_success(request: object) -> None:
                    if not isinstance(request, dict):
                        raise TypeError(f"OCR 返回结果格式不正确：{type(request)!r}")
                    self._apply_selected_experiment(request)
                    request.setdefault("source", str(image_path))
                    self._render_ocr_result(request)
                    self.ocr_preview.setPlainText(json.dumps(request, ensure_ascii=False, indent=2))
                    self._set_status("OCR 识别完成，请检查并修正结构化草稿。")

                self._begin_background_task(
                    "正在识别手写图片...",
                    processing_word="Thinking",
                    job=job,
                    on_success=handle_success,
                )
            except Exception as exc:
                self._show_error(exc)

        def _generate_from_ocr_preview(self) -> None:
            try:
                preview_text = self.ocr_preview.toPlainText().strip()
                if not preview_text:
                    raise ValueError("请先完成手写识别或粘贴结构化草稿。")
                request = json.loads(preview_text)
                self._apply_selected_experiment(request)
                self._apply_ocr_uncertainties_to_request(request)
                if not request.get("student"):
                    request["student"] = self._current_student()
                request["options"] = self._current_options()
                self.ocr_preview.setPlainText(json.dumps(request, ensure_ascii=False, indent=2))
                self._render_ocr_result(request)
                report_note = self._report_generation_note("ocr")
                if report_note:
                    request["report_generation_note"] = report_note
                self._run_generation(request)
            except Exception as exc:
                self._show_error(exc)

        def _report_generation_note(self, scope: str) -> str:
            checkbox = getattr(self, f"{scope}_report_note_checkbox", None)
            note_input = getattr(self, f"{scope}_report_note_input", None)
            if checkbox is None or note_input is None or not checkbox.isChecked():
                return ""
            return note_input.toPlainText().strip()

        def _apply_ocr_uncertainties_to_request(self, request: dict) -> None:
            controls = getattr(self, "ocr_uncertainty_controls", {})
            if not controls:
                return
            data = request.setdefault("data", {})
            fields = self._selected_experiment().get("fields") or {}
            for field_name, control in controls.items():
                field_meta = fields.get(field_name, {})
                field_data = data.get(field_name, {})
                unit, values = self._preview_field_unit_values(field_data, field_meta)
                if isinstance(field_data, dict):
                    updated_field_data = dict(field_data)
                    updated_field_data.setdefault("unit", unit)
                    updated_field_data.setdefault("values", values)
                else:
                    updated_field_data = {"unit": unit, "values": values}
                uncertainty = control.uncertainty()
                updated_field_data["b_uncertainty"] = uncertainty or {"enabled": False}
                data[field_name] = updated_field_data

        def _run_generation(self, request: dict) -> None:
            settings = self._collect_settings()
            save_settings(settings)
            use_llm = self.use_llm_checkbox.isChecked()

            def job() -> dict:
                return generate_report(request, settings, use_llm=use_llm)

            def handle_success(result: object) -> None:
                if not isinstance(result, dict):
                    raise TypeError(f"报告生成结果格式不正确：{type(result)!r}")
                self._latest_report_path = result["report_path"]
                self.report_path_label.setText(f"最近报告：{result['report_path']}")
                warning_text = "；".join(result["warnings"]) if result["warnings"] else "无"
                self._set_status(f"生成完成：{result['run_id']} | 警告：{warning_text}")
                QMessageBox.information(self, "生成完成", f"报告已生成：\n{result['report_path']}")

            self._begin_background_task(
                "正在生成报告...",
                processing_word="Cooking",
                job=job,
                on_success=handle_success,
            )

        def _current_student(self) -> dict:
            return {
                "name": self.student_name_input.text().strip(),
                "student_id": self.student_id_input.text().strip(),
                "class_name": self.class_name_input.text().strip(),
                "date": self.date_input.date().toString("yyyy-MM-dd"),
            }

        def _current_options(self) -> dict:
            return {
                "include_thinking": self.include_thinking_checkbox.isChecked(),
                "include_raw_appendix": self.include_raw_appendix_checkbox.isChecked(),
                "force_computer_plot": self.force_plot_checkbox.isChecked(),
                "forced_plot_count": self.force_plot_count_input.value(),
            }

        def _selected_experiment_id(self) -> str:
            experiment_id = self.experiment_combo.currentData()
            return str(experiment_id or "exp_001")

        def _apply_selected_experiment(self, request: dict) -> None:
            request["experiment_id"] = self._selected_experiment_id()

        def _selected_experiment(self) -> dict:
            return get_experiment(self._selected_experiment_id())

        def _manual_layout_profile(self) -> dict:
            field_count = len((self._selected_experiment().get("fields") or {}))
            dense = field_count >= 4
            available_width = 0
            if hasattr(self, "manual_scroll_area") and self.manual_scroll_area.viewport() is not None:
                parent = self.manual_scroll_area.parentWidget()
                if parent is not None:
                    available_width = parent.width()
            if available_width <= 0 and hasattr(self, "tabs"):
                available_width = self.tabs.width()
            if available_width <= 0:
                available_width = max(0, self.width() - self._s(420, minimum=360))
            available_width = max(0, available_width - self._s(34, minimum=24))
            if dense:
                return {
                    "dense": True,
                    "content_width": min(self._s(1120, minimum=960), max(self._s(760, minimum=680), available_width)),
                    "viewport_height": self._s(480, minimum=400),
                    "vertical_policy": Qt.ScrollBarAlwaysOn,
                }
            return {
                "dense": False,
                "content_width": min(self._s(980, minimum=860), max(self._s(700, minimum=620), available_width)),
                "viewport_height": self._s(460, minimum=360),
                "vertical_policy": Qt.ScrollBarAsNeeded,
            }

        def _apply_manual_layout_profile(self, *, reset_scroll: bool = False) -> None:
            if not hasattr(self, "manual_scroll_content"):
                return
            profile = self._manual_layout_profile()
            content_width = profile["content_width"]
            viewport_height = profile["viewport_height"]
            is_dense = profile["dense"]

            self.manual_scroll_area.setVerticalScrollBarPolicy(profile["vertical_policy"])
            self.manual_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            if is_dense:
                self.manual_scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self.manual_scroll_area.setMinimumHeight(viewport_height)
            else:
                self.manual_scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self.manual_scroll_area.setMinimumHeight(viewport_height)

            self.manual_scroll_content.setMinimumWidth(content_width)
            if hasattr(self, "manual_photo_card"):
                self.manual_photo_card.setMinimumWidth(content_width)
            if hasattr(self, "manual_student_card"):
                self.manual_student_card.setMinimumWidth(content_width)
            self.manual_fields_container.setMinimumWidth(content_width)
            if hasattr(self, "manual_footer_container"):
                self.manual_footer_container.setMinimumWidth(content_width)
            for block in self.manual_input_blocks.values():
                block.setMinimumWidth(content_width)
            if is_dense:
                self.manual_scroll_content.setMinimumHeight(self.manual_scroll_content.sizeHint().height())
            else:
                self.manual_scroll_content.setMinimumHeight(0)
            self.manual_scroll_content.updateGeometry()
            if reset_scroll and hasattr(self, "manual_scroll_area"):
                self.manual_scroll_area.verticalScrollBar().setValue(0)
                self.manual_scroll_area.horizontalScrollBar().setValue(0)

        def _resize_ocr_table(self) -> None:
            if not hasattr(self, "ocr_result_table"):
                return
            self.ocr_result_table.setColumnWidth(6, self._s(560, minimum=440))
            self.ocr_result_table.resizeRowsToContents()
            for row_index in range(self.ocr_result_table.rowCount()):
                cell_widget = self.ocr_result_table.cellWidget(row_index, 6)
                widget_height = cell_widget.sizeHint().height() if cell_widget is not None else 0
                row_height = max(self._s(30, minimum=26), widget_height + self._s(6, minimum=4))
                self.ocr_result_table.setRowHeight(row_index, row_height)
            self.ocr_result_table.setFixedHeight(self._s(220, minimum=180))
            if hasattr(self, "ocr_preview_card"):
                self.ocr_preview_card.adjustSize()
                self.ocr_preview_card.updateGeometry()

        def _refresh_experiment_dependent_ui(self) -> None:
            if hasattr(self, "manual_fields_layout"):
                self._rebuild_manual_inputs()
            elif hasattr(self, "manual_scroll_content"):
                self._apply_manual_layout_profile(reset_scroll=True)
            if hasattr(self, "ocr_warning_label"):
                self.ocr_warning_label.setText(f"当前 OCR 模板：{self._selected_experiment().get('name', '')}")

        def _rebuild_manual_inputs(self) -> None:
            if not hasattr(self, "manual_fields_layout"):
                return
            while self.manual_fields_layout.count():
                item = self.manual_fields_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.manual_input_blocks = {}
            experiment = self._selected_experiment()
            for field_name, field_meta in (experiment.get("fields") or {}).items():
                unit_options = field_meta.get("accepted_units") or [field_meta.get("base_unit") or ""]
                title = field_meta.get("label") or field_name
                placeholder = f"输入{title}数据，用逗号分隔"
                block = MeasurementInputBlock(title, unit_options, placeholder, self._ui_scale, self.manual_fields_container)
                self.manual_input_blocks[field_name] = block
                self.manual_fields_layout.addWidget(block)
            self._apply_manual_layout_profile(reset_scroll=True)

        def resizeEvent(self, event) -> None:
            super().resizeEvent(event)
            if hasattr(self, "manual_scroll_content"):
                self._apply_manual_layout_profile(reset_scroll=False)

        def _render_ocr_result(self, request: dict) -> None:
            experiment_id = request.get("experiment_id") or self._selected_experiment_id()
            experiment = get_experiment(str(experiment_id))
            data = request.get("data") or {}
            ocr_meta = request.get("ocr_meta") or {}
            warnings = []
            for item in request.get("warnings") or []:
                warnings.append(str(item))
            for item in ocr_meta.get("warnings") or []:
                warnings.append(str(item))
            warning_text = "；".join(warnings) if warnings else "无 warning。"
            self.ocr_warning_label.setText(f"Warning：{warning_text}")

            fields = experiment.get("fields") or {}
            field_names = [*fields.keys(), *[key for key in data.keys() if key not in fields]]
            recognized_cells = ocr_meta.get("recognized_cells") or []
            self.ocr_uncertainty_controls = {}
            self.ocr_result_table.setRowCount(len(field_names))
            for row_index, field_name in enumerate(field_names):
                field_meta = fields.get(field_name, {})
                field_data = data.get(field_name, {})
                unit, values = self._preview_field_unit_values(field_data, field_meta)
                raw_values = [str(cell.get("raw")) for cell in recognized_cells if cell.get("field") == field_name and cell.get("raw") not in (None, "")]
                confidences = [cell.get("confidence") for cell in recognized_cells if cell.get("field") == field_name and isinstance(cell.get("confidence"), (int, float))]
                confidence_text = f"{sum(confidences) / len(confidences):.2f}" if confidences else ""
                row_values = [
                    field_name,
                    field_meta.get("label") or field_name,
                    unit,
                    self._preview_values_text(values),
                    ", ".join(raw_values),
                    confidence_text,
                ]
                for column_index, value in enumerate(row_values):
                    self.ocr_result_table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
                control = OcrUncertaintyControl(field_meta.get("label") or field_name, unit, self._ui_scale, self.ocr_result_table)
                if isinstance(field_data, dict):
                    control.set_uncertainty(field_data.get("b_uncertainty"))
                self.ocr_uncertainty_controls[field_name] = control
                self.ocr_result_table.setCellWidget(row_index, 6, control)
                self.ocr_result_table.setRowHeight(row_index, max(self._s(46, minimum=40), control.sizeHint().height() + self._s(10, minimum=6)))
            self.ocr_result_table.resizeColumnsToContents()
            self._resize_ocr_table()

        def _preview_field_unit_values(self, field_data: object, field_meta: dict) -> tuple[str, list[object]]:
            if isinstance(field_data, dict):
                unit = field_data.get("unit") or field_meta.get("base_unit") or ""
                values = field_data.get("values") or []
            elif isinstance(field_data, list):
                unit = field_meta.get("base_unit") or ""
                values = field_data
            elif field_data not in (None, ""):
                unit = field_meta.get("base_unit") or ""
                values = [field_data]
            else:
                unit = field_meta.get("base_unit") or ""
                values = []
            return str(unit), list(values)

        def _preview_values_text(self, values: list[object]) -> str:
            return ", ".join("" if value is None else str(value) for value in values)

        def _parse_number_list(self, text: str) -> list[float]:
            values = []
            for item in text.replace("，", ",").split(","):
                item = item.strip()
                if item:
                    values.append(float(item))
            return values

        def _show_error(self, exc: Exception) -> None:
            self._set_busy(False, "")
            self._set_status(f"发生错误：{exc}")
            QMessageBox.critical(self, "错误", str(exc))

        def _set_status(self, text: str) -> None:
            self.status_label.setText(text)

        def _set_busy(self, busy: bool, message: str, *, processing_word: str | None = None) -> None:
            if busy == self._busy_active:
                if busy and hasattr(self, "processing_indicator") and not self.processing_indicator.isVisible():
                    self.processing_indicator.start(processing_word)
                if message:
                    self._set_status(message)
                return

            self._busy_active = busy

            for widget in getattr(self, "_busy_widgets", []):
                widget.setEnabled(not busy)

            if hasattr(self, "processing_indicator"):
                if busy:
                    self.processing_indicator.start(processing_word)
                else:
                    self.processing_indicator.stop()

            if message:
                self._set_status(message)

    _set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app_icon = QIcon(str(app_icon_path()))
    app.setApplicationName("PhyExpAssistant")
    app.setApplicationDisplayName("PhyExpAssistant")
    app.setWindowIcon(app_icon)
    window = MainWindow()
    window.setWindowIcon(app_icon)
    window.show()
    return app.exec()


def _build_header(settings_button: object, processing_indicator: object, scale: float):
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

    frame = QFrame()
    frame.setObjectName("headerCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(_scaled(20, scale, minimum=14), _scaled(18, scale, minimum=12), _scaled(20, scale, minimum=14), _scaled(18, scale, minimum=12))
    top_row = QHBoxLayout()
    top_row.setContentsMargins(0, 0, 0, 0)
    top_row.setSpacing(_scaled(12, scale, minimum=8))
    title_box = QVBoxLayout()
    title_box.setContentsMargins(0, 0, 0, 0)
    title_box.setSpacing(_scaled(2, scale, minimum=1))
    title = QLabel("PhyExpAssistant")
    title.setObjectName("headerTitle")
    subtitle = QLabel("Powered by PatriciaOfEnd & LyCecilion - 大学物理实验轻量化、自动化解决方案")
    subtitle.setObjectName("headerSubtitle")
    title_box.addWidget(title)
    title_box.addWidget(subtitle)
    top_row.addLayout(title_box, 1)
    top_row.addWidget(processing_indicator, 0)
    top_row.addWidget(settings_button, 0)
    layout.addLayout(top_row)
    return frame

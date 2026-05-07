from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import json
import sys

from .llm_client import LLMClient, LLMError
from .paths import app_home, resolve_input_path
from .settings import Settings, load_settings, save_settings
from .workflow import (
    B_UNCERTAINTY_METHODS,
    WorkflowError,
    generate_report,
    load_request_json,
    manual_request,
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
        QScrollArea#mainScrollArea,
        QScrollArea#leftScrollArea,
        QWidget#mainContent,
        QWidget#leftPanelContent {{
            background: {theme.background};
            border: none;
        }}
        QScrollArea#leftScrollArea {{
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


def launch_ui(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtCore import QDate, QEvent, Qt, QUrl
        from PySide6.QtGui import QColor, QDesktopServices, QFont
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
            "QToolButton": QToolButton,
            "QVBoxLayout": QVBoxLayout,
            "QWidget": QWidget,
            "QDate": QDate,
            "QEvent": QEvent,
            "Qt": Qt,
            "QUrl": QUrl,
            "QColor": QColor,
            "QDesktopServices": QDesktopServices,
            "QFont": QFont,
        }
    )

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

            layout = QVBoxLayout(self)
            layout.setSpacing(_scaled(10, scale, minimum=6))

            top_row = QHBoxLayout()
            top_row.setSpacing(_scaled(8, scale, minimum=6))
            self.unit_combo = QComboBox(self)
            self.unit_combo.addItems(unit_options)
            self.values_input = QLineEdit(self)
            self.values_input.setPlaceholderText(values_placeholder)
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
            self.division_input.setFixedWidth(_scaled(150, scale, minimum=110))
            self.division_unit_label = QLabel(self.unit_combo.currentText(), self)
            self.method_combo = QComboBox(self)
            self.method_combo.addItem(B_UNCERTAINTY_METHODS["half_division_uniform"]["label"], "half_division_uniform")
            self.method_combo.addItem(B_UNCERTAINTY_METHODS["division_uniform"]["label"], "division_uniform")
            self.method_combo.setFixedWidth(_scaled(160, scale, minimum=128))
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
            self._busy_cursor_active = False
            app = QApplication.instance()
            self._ui_scale = self._compute_ui_scale(app)
            self._theme_palette = build_theme_palette(self.settings)
            self.setWindowTitle("PhyExpAssistant Demo")
            self.setMinimumSize(self._s(760, minimum=620), self._s(520, minimum=430))
            self.resize(self._s(1040, minimum=820), self._s(680, minimum=560))
            self._build_ui(app)
            self._apply_theme()
            self._apply_settings_to_form()
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

            scroll_area = QScrollArea(self)
            scroll_area.setObjectName("mainScrollArea")
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.setCentralWidget(scroll_area)

            central = QWidget()
            central.setObjectName("mainContent")
            central.setMinimumSize(self._s(900, minimum=620), self._s(720, minimum=520))
            scroll_area.setWidget(central)

            root_layout = QVBoxLayout(central)
            root_layout.setContentsMargins(self._s(16), self._s(16), self._s(16), self._s(16))
            root_layout.setSpacing(self._s(12, minimum=8))

            self.theme_button = QToolButton()
            self.theme_button.setObjectName("themeButton")
            self.theme_button.setText("设置")
            self.theme_button.clicked.connect(self._open_theme_dialog)
            root_layout.addWidget(_build_header(self.theme_button, self._ui_scale))

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

            student_card = QGroupBox("学生信息")
            student_layout = QFormLayout(student_card)
            student_layout.setLabelAlignment(Qt.AlignRight)

            self.student_name_input = QLineEdit()
            self.student_id_input = QLineEdit()
            self.class_name_input = QLineEdit()
            self.date_input = FlatDatePicker(self._ui_scale)
            self.date_input.setDate(QDate.currentDate())

            student_layout.addRow("姓名", self.student_name_input)
            student_layout.addRow("学号", self.student_id_input)
            student_layout.addRow("班级", self.class_name_input)
            student_layout.addRow("日期", self.date_input)
            left_column.addWidget(student_card)

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
            self.load_sample_button = QPushButton("加载样例")
            self.load_sample_button.clicked.connect(self._load_sample)
            self.open_output_button = QPushButton("打开输出目录")
            self.open_output_button.clicked.connect(self._open_output_dir)
            self.open_report_button = QPushButton("打开最近报告")
            self.open_report_button.clicked.connect(self._open_report)
            quick_layout.addWidget(self.load_sample_button, 0, 0)
            quick_layout.addWidget(self.open_output_button, 0, 1)
            quick_layout.addWidget(self.open_report_button, 1, 0, 1, 2)
            left_column.addWidget(quick_card)
            left_column.addStretch(1)

            self.tabs = QTabWidget()
            right_column.addWidget(self.tabs, 1)

            self.tabs.addTab(self._build_json_tab(), "JSON / CSV")
            self.tabs.addTab(self._build_manual_tab(), "手动录入")
            self.tabs.addTab(self._build_ocr_tab(), "手写识别")

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

        def _build_json_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setSpacing(self._s(14, minimum=8))

            json_card = QGroupBox("从 JSON 生成报告")
            json_layout = QHBoxLayout(json_card)
            self.json_path_input = QLineEdit()
            self.json_path_input.setPlaceholderText("选择 JSON 输入文件")
            json_browse = QPushButton("浏览")
            json_browse.clicked.connect(lambda: self._pick_file(self.json_path_input, "JSON 文件 (*.json)"))
            json_generate = QPushButton("生成 JSON 报告")
            json_generate.setObjectName("primaryButton")
            json_generate.clicked.connect(self._generate_from_json)
            json_layout.addWidget(self.json_path_input, 1)
            json_layout.addWidget(json_browse)
            json_layout.addWidget(json_generate)

            csv_card = QGroupBox("从 CSV 生成报告")
            csv_layout = QHBoxLayout(csv_card)
            self.csv_path_input = QLineEdit()
            self.csv_path_input.setPlaceholderText("选择 CSV 输入文件")
            csv_browse = QPushButton("浏览")
            csv_browse.clicked.connect(lambda: self._pick_file(self.csv_path_input, "CSV 文件 (*.csv)"))
            csv_generate = QPushButton("生成 CSV 报告")
            csv_generate.setObjectName("primaryButton")
            csv_generate.clicked.connect(self._generate_from_csv)
            csv_layout.addWidget(self.csv_path_input, 1)
            csv_layout.addWidget(csv_browse)
            csv_layout.addWidget(csv_generate)

            layout.addWidget(json_card)
            layout.addWidget(csv_card)
            layout.addStretch(1)
            return tab

        def _build_manual_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setSpacing(self._s(14, minimum=8))

            self.length_input_block = MeasurementInputBlock(
                "摆长 L",
                ["m", "cm", "mm"],
                "0.5, 0.6, 0.7",
                self._ui_scale,
                tab,
            )
            self.period_input_block = MeasurementInputBlock(
                "周期 T",
                ["s", "ms"],
                "1.42, 1.55, 1.67",
                self._ui_scale,
                tab,
            )

            manual_generate = QPushButton("生成手动录入报告")
            manual_generate.setObjectName("primaryButton")
            manual_generate.clicked.connect(self._generate_from_manual)

            layout.addWidget(self.length_input_block)
            layout.addWidget(self.period_input_block)
            layout.addWidget(manual_generate)
            layout.addStretch(1)
            return tab

        def _build_ocr_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setSpacing(self._s(14, minimum=8))

            image_card = QGroupBox("手写图片识别")
            image_layout = QHBoxLayout(image_card)
            self.image_path_input = QLineEdit()
            self.image_path_input.setPlaceholderText("选择手写数据图片")
            image_browse = QPushButton("浏览")
            image_browse.clicked.connect(lambda: self._pick_file(self.image_path_input, "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"))
            ocr_button = QPushButton("LLM 识别")
            ocr_button.clicked.connect(self._run_ocr)
            image_layout.addWidget(self.image_path_input, 1)
            image_layout.addWidget(image_browse)
            image_layout.addWidget(ocr_button)

            preview_card = QGroupBox("识别结果草稿")
            preview_layout = QVBoxLayout(preview_card)
            self.ocr_preview = QPlainTextEdit()
            self.ocr_preview.setPlaceholderText("点击 LLM 识别后，这里会显示 JSON 草稿，用户可手动修正。")
            preview_layout.addWidget(self.ocr_preview)

            ocr_generate = QPushButton("使用当前草稿生成报告")
            ocr_generate.setObjectName("primaryButton")
            ocr_generate.clicked.connect(self._generate_from_ocr_preview)

            layout.addWidget(image_card)
            layout.addWidget(preview_card, 1)
            layout.addWidget(ocr_generate)
            return tab

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

        def _load_sample(self) -> None:
            sample = resolve_input_path("data/samples/pendulum.json")
            self.json_path_input.setText(str(sample))
            self.tabs.setCurrentIndex(0)
            self._set_status("已加载样例 JSON 路径")

        def _pick_file(self, target: QLineEdit, filter_text: str) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件", str(Path.cwd()), filter_text)
            if path:
                target.setText(path)

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

        def _generate_from_json(self) -> None:
            try:
                request = load_request_json(resolve_input_path(self.json_path_input.text().strip()))
                self._run_generation(request)
            except Exception as exc:
                self._show_error(exc)

        def _generate_from_csv(self) -> None:
            try:
                from .workflow import load_request_csv

                student = self._current_student()
                options = self._current_options()
                request = load_request_csv(resolve_input_path(self.csv_path_input.text().strip()), student, options)
                self._run_generation(request)
            except Exception as exc:
                self._show_error(exc)

        def _generate_from_manual(self) -> None:
            try:
                request = manual_request(
                    self._current_student(),
                    self.length_input_block.values(),
                    self.length_input_block.unit(),
                    self.period_input_block.values(),
                    self.period_input_block.unit(),
                    self._current_options(),
                    length_uncertainty=self.length_input_block.uncertainty(),
                    period_uncertainty=self.period_input_block.uncertainty(),
                )
                self._run_generation(request)
            except Exception as exc:
                self._show_error(exc)

        def _run_ocr(self) -> None:
            try:
                settings = self._collect_settings()
                if not settings.is_llm_ready:
                    raise LLMError("请先填写 Base URL、Model 和 API Key。")
                image_path = resolve_input_path(self.image_path_input.text().strip())
                self._set_busy(True, "正在识别手写图片...")
                request = LLMClient(settings).extract_handwritten_data(image_path, "exp_001")
                request.setdefault("source", str(image_path))
                self.ocr_preview.setPlainText(json.dumps(request, ensure_ascii=False, indent=2))
                self._set_status("OCR 识别完成，请检查并修正 JSON 草稿。")
            except Exception as exc:
                self._show_error(exc)
            finally:
                self._set_busy(False, "")

        def _generate_from_ocr_preview(self) -> None:
            try:
                request = json.loads(self.ocr_preview.toPlainText())
                if not request.get("student"):
                    request["student"] = self._current_student()
                request.setdefault("options", self._current_options())
                self._run_generation(request)
            except Exception as exc:
                self._show_error(exc)

        def _run_generation(self, request: dict) -> None:
            settings = self._collect_settings()
            save_settings(settings)
            use_llm = self.use_llm_checkbox.isChecked()
            self._set_busy(True, "正在生成报告...")
            try:
                result = generate_report(request, settings, use_llm=use_llm)
                self._latest_report_path = result["report_path"]
                self.report_path_label.setText(f"最近报告：{result['report_path']}")
                warning_text = "；".join(result["warnings"]) if result["warnings"] else "无"
                self._set_status(f"生成完成：{result['run_id']} | 警告：{warning_text}")
                QMessageBox.information(self, "生成完成", f"报告已生成：\n{result['report_path']}")
            except Exception as exc:
                self._show_error(exc)
            finally:
                self._set_busy(False, "")

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
            }

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

        def _set_busy(self, busy: bool, message: str) -> None:
            if busy and not self._busy_cursor_active:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                self._busy_cursor_active = True
            elif not busy and self._busy_cursor_active:
                QApplication.restoreOverrideCursor()
                self._busy_cursor_active = False
            if message:
                self._set_status(message)

    app = QApplication.instance() or QApplication([sys.argv[0]])
    window = MainWindow()
    window.show()
    return app.exec()


def _build_header(settings_button: object, scale: float):
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
    title = QLabel("PhyExpAssistant Demo")
    title.setObjectName("headerTitle")
    subtitle = QLabel("扁平化、本地优先、Windows / Linux 双端适配")
    subtitle.setObjectName("headerSubtitle")
    title_box.addWidget(title)
    title_box.addWidget(subtitle)
    top_row.addLayout(title_box, 1)
    top_row.addWidget(settings_button, 0)
    layout.addLayout(top_row)
    return frame

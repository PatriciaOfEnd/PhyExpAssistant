from __future__ import annotations

from pathlib import Path
import math
import struct
import zlib


Color = tuple[int, int, int]

WHITE: Color = (255, 255, 255)
INK: Color = (36, 42, 54)
MUTED: Color = (116, 128, 145)
GRID: Color = (220, 226, 235)
ACCENT: Color = (40, 104, 220)
FIT: Color = (220, 80, 80)


def write_pendulum_fit_plot(
    path: Path,
    lengths_m: list[float],
    periods_s: list[float],
    slope: float,
    intercept: float,
    r2: float | None,
) -> dict:
    x_values = lengths_m
    y_values = [period**2 for period in periods_s]
    caption = "T²-L 线性拟合图"
    write_xy_fit_plot(path, x_values, y_values, slope, intercept)
    return {
        "key": "pendulum_fit",
        "path": str(path),
        "caption": caption,
        "description": "横轴为摆长 L，纵轴为周期平方 T²，红线为线性拟合结果。",
        "r2": r2,
    }


def write_xy_fit_plot(path: Path, x_values: list[float], y_values: list[float], slope: float, intercept: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1000, 650
    margin_left, margin_right, margin_top, margin_bottom = 95, 45, 55, 85
    image = _new_canvas(width, height, WHITE)

    if not x_values or not y_values:
        _write_png(path, image, width, height)
        return

    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    fit_y_values = [slope * x_min + intercept, slope * x_max + intercept]
    y_min = min(y_min, *fit_y_values)
    y_max = max(y_max, *fit_y_values)
    x_pad = (x_max - x_min) * 0.08 or 0.1
    y_pad = (y_max - y_min) * 0.12 or 0.1
    x_min -= x_pad
    x_max += x_pad
    y_min -= y_pad
    y_max += y_pad

    plot_left = margin_left
    plot_right = width - margin_right
    plot_top = margin_top
    plot_bottom = height - margin_bottom

    def map_x(value: float) -> int:
        return round(plot_left + (value - x_min) / (x_max - x_min) * (plot_right - plot_left))

    def map_y(value: float) -> int:
        return round(plot_bottom - (value - y_min) / (y_max - y_min) * (plot_bottom - plot_top))

    _draw_rect(image, width, plot_left, plot_top, plot_right, plot_bottom, GRID)
    for tick in range(6):
        x = round(plot_left + tick / 5 * (plot_right - plot_left))
        y = round(plot_bottom - tick / 5 * (plot_bottom - plot_top))
        _draw_line(image, width, x, plot_top, x, plot_bottom, GRID)
        _draw_line(image, width, plot_left, y, plot_right, y, GRID)
        _draw_line(image, width, x, plot_bottom, x, plot_bottom + 7, MUTED)
        _draw_line(image, width, plot_left - 7, y, plot_left, y, MUTED)

    _draw_line(image, width, plot_left, plot_bottom, plot_right, plot_bottom, INK, thickness=2)
    _draw_line(image, width, plot_left, plot_top, plot_left, plot_bottom, INK, thickness=2)

    fit_x1, fit_x2 = x_min, x_max
    fit_y1, fit_y2 = slope * fit_x1 + intercept, slope * fit_x2 + intercept
    _draw_line(image, width, map_x(fit_x1), map_y(fit_y1), map_x(fit_x2), map_y(fit_y2), FIT, thickness=3)

    for x_value, y_value in zip(x_values, y_values):
        _draw_circle(image, width, map_x(x_value), map_y(y_value), 6, ACCENT)
        _draw_circle(image, width, map_x(x_value), map_y(y_value), 3, WHITE)

    _write_png(path, image, width, height)


def _new_canvas(width: int, height: int, color: Color) -> bytearray:
    red, green, blue = color
    return bytearray([red, green, blue] * width * height)


def _set_pixel(image: bytearray, width: int, x: int, y: int, color: Color) -> None:
    if x < 0 or y < 0:
        return
    offset = (y * width + x) * 3
    if offset < 0 or offset + 2 >= len(image):
        return
    image[offset : offset + 3] = bytes(color)


def _draw_rect(image: bytearray, width: int, left: int, top: int, right: int, bottom: int, color: Color) -> None:
    _draw_line(image, width, left, top, right, top, color)
    _draw_line(image, width, right, top, right, bottom, color)
    _draw_line(image, width, right, bottom, left, bottom, color)
    _draw_line(image, width, left, bottom, left, top, color)


def _draw_line(
    image: bytearray,
    width: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: Color,
    *,
    thickness: int = 1,
) -> None:
    dx = abs(x2 - x1)
    dy = -abs(y2 - y1)
    step_x = 1 if x1 < x2 else -1
    step_y = 1 if y1 < y2 else -1
    error = dx + dy
    x, y = x1, y1
    radius = max(0, thickness // 2)
    while True:
        for px in range(x - radius, x + radius + 1):
            for py in range(y - radius, y + radius + 1):
                _set_pixel(image, width, px, py, color)
        if x == x2 and y == y2:
            break
        double_error = 2 * error
        if double_error >= dy:
            error += dy
            x += step_x
        if double_error <= dx:
            error += dx
            y += step_y


def _draw_circle(image: bytearray, width: int, center_x: int, center_y: int, radius: int, color: Color) -> None:
    radius_squared = radius * radius
    for y in range(center_y - radius, center_y + radius + 1):
        for x in range(center_x - radius, center_x + radius + 1):
            if (x - center_x) ** 2 + (y - center_y) ** 2 <= radius_squared:
                _set_pixel(image, width, x, y, color)


def _write_png(path: Path, image: bytearray, width: int, height: int) -> None:
    rows = []
    row_bytes = width * 3
    for y in range(height):
        start = y * row_bytes
        rows.append(b"\x00" + bytes(image[start : start + row_bytes]))
    raw = b"".join(rows)
    with path.open("wb") as file:
        file.write(b"\x89PNG\r\n\x1a\n")
        _write_chunk(file, b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        _write_chunk(file, b"IDAT", zlib.compress(raw, level=9))
        _write_chunk(file, b"IEND", b"")


def _write_chunk(file, chunk_type: bytes, data: bytes) -> None:
    file.write(struct.pack(">I", len(data)))
    file.write(chunk_type)
    file.write(data)
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc)
    file.write(struct.pack(">I", crc & 0xFFFFFFFF))

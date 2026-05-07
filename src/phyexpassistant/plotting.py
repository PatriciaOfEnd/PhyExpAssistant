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


def write_safe_plot(path: Path, plot_spec: dict, data_context: dict) -> dict:
    plot_type = str(plot_spec.get("plot_type") or "").strip()
    if plot_type not in {"scatter", "line", "scatter_with_linear_fit", "bar"}:
        raise ValueError(f"不支持的 safe_spec.plot_type：{plot_type!r}")

    x_spec = plot_spec.get("x") or {}
    y_spec = plot_spec.get("y") or {}
    x_values = _series_from_spec(x_spec, data_context)
    y_values = _series_from_spec(y_spec, data_context)
    if not x_values:
        x_values = [float(index + 1) for index in range(len(y_values))]
    row_count = min(len(x_values), len(y_values))
    if row_count == 0:
        raise ValueError("safe_spec 没有可绘制的数据点。")
    x_values = x_values[:row_count]
    y_values = y_values[:row_count]

    fit = None
    if plot_type == "scatter_with_linear_fit" or (plot_spec.get("fit") or {}).get("enabled"):
        fit = _linear_fit_for_plot(x_values, y_values)

    _write_xy_plot(path, x_values, y_values, plot_type=plot_type, fit=fit)
    caption = plot_spec.get("caption") or plot_spec.get("title") or "计算机绘图"
    return {
        "key": str(plot_spec.get("key") or path.stem),
        "path": str(path),
        "caption": str(caption),
        "description": str(plot_spec.get("description") or _plot_description(plot_spec, fit)),
        "position": str(plot_spec.get("position") or "after_calculation_results"),
        "safe_spec": plot_spec,
    }


def _write_xy_plot(
    path: Path,
    x_values: list[float],
    y_values: list[float],
    *,
    plot_type: str,
    fit: dict | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1000, 650
    margin_left, margin_right, margin_top, margin_bottom = 95, 45, 55, 85
    image = _new_canvas(width, height, WHITE)

    if not x_values or not y_values:
        _write_png(path, image, width, height)
        return

    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    if fit:
        slope = float(fit.get("slope") or 0.0)
        intercept = float(fit.get("intercept") or 0.0)
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

    if fit:
        slope = float(fit.get("slope") or 0.0)
        intercept = float(fit.get("intercept") or 0.0)
        fit_x1, fit_x2 = x_min, x_max
        fit_y1, fit_y2 = slope * fit_x1 + intercept, slope * fit_x2 + intercept
        _draw_line(image, width, map_x(fit_x1), map_y(fit_y1), map_x(fit_x2), map_y(fit_y2), FIT, thickness=3)

    if plot_type == "line":
        for first, second in zip(zip(x_values, y_values), zip(x_values[1:], y_values[1:])):
            _draw_line(image, width, map_x(first[0]), map_y(first[1]), map_x(second[0]), map_y(second[1]), ACCENT, thickness=3)
    elif plot_type == "bar":
        bar_width = max(4, round((plot_right - plot_left) / max(1, len(x_values) * 3)))
        baseline = map_y(0 if y_min <= 0 <= y_max else y_min)
        for x_value, y_value in zip(x_values, y_values):
            x_center = map_x(x_value)
            y_top = map_y(y_value)
            for x in range(x_center - bar_width, x_center + bar_width + 1):
                _draw_line(image, width, x, baseline, x, y_top, ACCENT)

    for x_value, y_value in zip(x_values, y_values):
        _draw_circle(image, width, map_x(x_value), map_y(y_value), 6, ACCENT)
        _draw_circle(image, width, map_x(x_value), map_y(y_value), 3, WHITE)

    _write_png(path, image, width, height)


def _series_from_spec(axis_spec: dict, data_context: dict) -> list[float]:
    source = str(axis_spec.get("source") or "").strip()
    if not source:
        return []
    values = _resolve_source(source, data_context)
    if isinstance(values, dict) and "values" in values:
        values = values["values"]
    if not isinstance(values, list):
        return []
    transform = str(axis_spec.get("transform") or "identity").strip()
    return [_apply_transform(float(value), transform) for value in values if value not in (None, "")]


def _resolve_source(source: str, data_context: dict):
    parts = source.split(".")
    if parts and parts[0] == "normalized_input":
        parts = parts[1:]
    current = data_context
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


def _apply_transform(value: float, transform: str) -> float:
    if transform in {"", "identity", "none"}:
        return value
    if transform == "square":
        return value * value
    if transform == "sqrt":
        return math.sqrt(value)
    if transform == "abs":
        return abs(value)
    if transform == "log10":
        return math.log10(value)
    raise ValueError(f"不支持的 safe_spec transform：{transform!r}")


def _linear_fit_for_plot(x_values: list[float], y_values: list[float]) -> dict:
    count = min(len(x_values), len(y_values))
    if count < 2:
        return {"slope": 0.0, "intercept": y_values[0] if y_values else 0.0, "r2": None}
    x_values = x_values[:count]
    y_values = y_values[:count]
    x_mean = sum(x_values) / count
    y_mean = sum(y_values) / count
    sxx = sum((x - x_mean) ** 2 for x in x_values)
    if sxx == 0:
        return {"slope": 0.0, "intercept": y_mean, "r2": None}
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    predictions = [slope * x + intercept for x in x_values]
    ss_res = sum((y - prediction) ** 2 for y, prediction in zip(y_values, predictions))
    ss_tot = sum((y - y_mean) ** 2 for y in y_values)
    r2 = None if ss_tot == 0 else 1 - ss_res / ss_tot
    return {"slope": slope, "intercept": intercept, "r2": r2}


def _plot_description(plot_spec: dict, fit: dict | None) -> str:
    x_label = (plot_spec.get("x") or {}).get("label") or "x"
    y_label = (plot_spec.get("y") or {}).get("label") or "y"
    description = f"横轴为 {x_label}，纵轴为 {y_label}。"
    if fit and fit.get("r2") is not None:
        description += f"线性拟合 R² = {fit['r2']:.4f}。"
    return description


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

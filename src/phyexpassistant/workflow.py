from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from statistics import mean, stdev
import csv
import json
import math
import uuid

from .docx_writer import write_docx
from .experiments import get_experiment
from .llm_client import LLMClient, LLMError
from .paths import output_root, resolve_input_path
from .plotting import write_pendulum_fit_plot
from .settings import Settings


OUTPUT_ROOT = output_root()

UNIT_FACTORS = {
    "m": 1.0,
    "cm": 0.01,
    "mm": 0.001,
    "s": 1.0,
    "ms": 0.001,
}

B_UNCERTAINTY_METHODS = {
    "half_division_uniform": {
        "label": "分度值/(2√3)",
        "description": "按半分度值均匀分布估计",
    },
    "division_uniform": {
        "label": "分度值/√3",
        "description": "按分度值均匀分布估计",
    },
}


class WorkflowError(RuntimeError):
    pass


def load_request_json(path: Path) -> dict:
    path = resolve_input_path(path)
    if not path.exists():
        raise WorkflowError(f"JSON 文件不存在：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return _with_defaults(data, source=str(path))


def load_request_csv(path: Path, student: dict, options: dict | None = None, experiment_id: str = "exp_001") -> dict:
    path = resolve_input_path(path)
    if not path.exists():
        raise WorkflowError(f"CSV 文件不存在：{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise WorkflowError("CSV 文件没有数据行。")

    length_values, length_unit = _read_csv_series(rows, ["length_m", "length_cm", "length_mm", "length"])
    period_values, period_unit = _read_csv_series(rows, ["period_s", "period_ms", "period"])
    request = {
        "experiment_id": experiment_id,
        "student": student,
        "options": options or {},
        "data": {
            "length": {"unit": length_unit, "values": length_values},
            "period": {"unit": period_unit, "values": period_values},
        },
    }
    return _with_defaults(request, source=str(path))


def manual_request(
    student: dict,
    length_values: list[float],
    length_unit: str,
    period_values: list[float],
    period_unit: str,
    options: dict | None = None,
    length_uncertainty: dict | None = None,
    period_uncertainty: dict | None = None,
) -> dict:
    request = {
        "experiment_id": "exp_001",
        "student": student,
        "options": options or {},
        "data": {
            "length": {"unit": length_unit, "values": length_values},
            "period": {"unit": period_unit, "values": period_values},
        },
    }
    if length_uncertainty:
        request["data"]["length"]["b_uncertainty"] = length_uncertainty
    if period_uncertainty:
        request["data"]["period"]["b_uncertainty"] = period_uncertainty
    return _with_defaults(request, source="manual")


def generate_report(request: dict, settings: Settings, *, use_llm: bool = True) -> dict:
    request = _with_defaults(request, source=request.get("source", "unknown"))
    experiment = get_experiment(request["experiment_id"])
    run_id = _make_run_id(request["experiment_id"])
    run_dir = OUTPUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    _write_json(run_dir / "input.request.json", request)

    normalized = normalize_request(request, experiment)
    _write_json(run_dir / "input.normalized.json", normalized)

    compute_result = compute_pendulum(normalized)
    figure = write_pendulum_fit_plot(
        run_dir / "figures" / "pendulum_fit.png",
        normalized["data"]["length_m"],
        normalized["data"]["period_s"],
        compute_result["fit"].get("slope") or 0.0,
        compute_result["fit"].get("intercept") or 0.0,
        compute_result["fit"].get("r2"),
    )
    compute_result["figures"] = [figure]
    _write_json(run_dir / "compute.result.json", compute_result)

    narrative = build_local_narrative(normalized, compute_result)
    if use_llm and settings.is_llm_ready:
        try:
            llm_narrative = LLMClient(settings).generate_narrative(normalized, compute_result)
            narrative.update(_sanitize_narrative(llm_narrative, narrative, compute_result))
        except LLMError as exc:
            warnings.append(f"LLM 文案生成失败，已使用本地模板：{exc}")
    elif use_llm:
        warnings.append("LLM 未配置，已使用本地模板生成报告文字。")
    _write_json(run_dir / "narrative.result.json", narrative)

    render_context = build_render_context(normalized, compute_result, narrative)
    validate_render_context(render_context, experiment["render_contract"])
    _write_json(run_dir / "render.context.json", render_context)

    report_path = run_dir / "report.docx"
    write_docx(report_path, render_context)


    manifest = {
        "run_id": run_id,
        "experiment_id": request["experiment_id"],
        "experiment_name": experiment["name"],
        "source": request.get("source"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": settings.model if settings.is_llm_ready and use_llm else None,
        "artifacts": {
            "request": str(run_dir / "input.request.json"),
            "normalized_input": str(run_dir / "input.normalized.json"),
            "compute_result": str(run_dir / "compute.result.json"),
            "narrative_result": str(run_dir / "narrative.result.json"),
            "render_context": str(run_dir / "render.context.json"),
            "report": str(report_path),
            "figures": [figure["path"]],
        },
        "warnings": warnings,
    }
    _write_json(run_dir / "manifest.json", manifest)
    return {"run_id": run_id, "run_dir": str(run_dir), "report_path": str(report_path), "warnings": warnings}


def normalize_request(request: dict, experiment: dict) -> dict:
    data = request.get("data") or {}
    length_m = _extract_series(data, "length", aliases=["length_m", "length_cm", "length_mm", "length_values"])
    period_s = _extract_series(data, "period", aliases=["period_s", "period_ms", "period_s_list", "period_values"])
    length_uncertainty = _normalize_b_uncertainty(data, "length", "m")
    period_uncertainty = _normalize_b_uncertainty(data, "period", "s")

    if len(length_m) != len(period_s):
        raise WorkflowError(f"摆长数据行数 {len(length_m)} 与周期数据行数 {len(period_s)} 不一致。")
    if len(length_m) < 2:
        raise WorkflowError("至少需要 2 组数据才能生成 demo 报告。")

    fields = experiment["fields"]
    rows = []
    for index, (length, period) in enumerate(zip(length_m, period_s), start=1):
        _check_range("length", length, fields["length"], index)
        _check_range("period", period, fields["period"], index)
        rows.append({"index": index, "length_m": length, "period_s": period})

    student = request["student"]
    return {
        "experiment_id": request["experiment_id"],
        "experiment_name": experiment["name"],
        "student": student,
        "options": request["options"],
        "data": {"length_m": length_m, "period_s": period_s},
        "uncertainties": {
            "length": length_uncertainty,
            "period": period_uncertainty,
        },
        "rows": rows,
    }


def compute_pendulum(normalized: dict) -> dict:
    rows = normalized["rows"]
    calc_rows = []
    g_values = []
    for row in rows:
        length = row["length_m"]
        period = row["period_s"]
        period_squared = period**2
        g_value = 4 * math.pi**2 * length / period_squared
        g_values.append(g_value)
        calc_rows.append(
            {
                "index": row["index"],
                "length_m": length,
                "period_s": period,
                "period_squared": period_squared,
                "g_value": g_value,
            }
        )

    g_mean = mean(g_values)
    g_std = stdev(g_values) if len(g_values) > 1 else 0.0
    g_a_uncertainty = g_std / math.sqrt(len(g_values)) if g_values else 0.0
    fit_result = _linear_fit(
        [row["length_m"] for row in rows],
        [row["period_s"] ** 2 for row in rows],
    )
    g_fit = 4 * math.pi**2 / fit_result["slope"] if fit_result["slope"] > 0 else None

    mean_length = mean([row["length_m"] for row in rows])
    mean_period = mean([row["period_s"] for row in rows])
    length_uncertainty = normalized.get("uncertainties", {}).get("length", {})
    period_uncertainty = normalized.get("uncertainties", {}).get("period", {})
    g_b_length_uncertainty = 0.0
    g_b_period_uncertainty = 0.0
    if length_uncertainty.get("enabled") and mean_length:
        g_b_length_uncertainty = abs(g_mean / mean_length) * length_uncertainty.get("standard", 0.0)
    if period_uncertainty.get("enabled") and mean_period:
        g_b_period_uncertainty = abs(2 * g_mean / mean_period) * period_uncertainty.get("standard", 0.0)
    g_b_uncertainty = math.sqrt(g_b_length_uncertainty**2 + g_b_period_uncertainty**2)
    g_uncertainty = math.sqrt(g_a_uncertainty**2 + g_b_uncertainty**2)

    return {
        "metrics": {
            "g_mean": {"value": g_mean, "unit": "m/s^2", "precision": 4},
            "g_std": {"value": g_std, "unit": "m/s^2", "precision": 4},
            "g_a_uncertainty": {"value": g_a_uncertainty, "unit": "m/s^2", "precision": 4},
            "g_b_length_uncertainty": {"value": g_b_length_uncertainty, "unit": "m/s^2", "precision": 4},
            "g_b_period_uncertainty": {"value": g_b_period_uncertainty, "unit": "m/s^2", "precision": 4},
            "g_b_uncertainty": {"value": g_b_uncertainty, "unit": "m/s^2", "precision": 4},
            "g_uncertainty": {"value": g_uncertainty, "unit": "m/s^2", "precision": 4},
            "g_fit": {"value": g_fit, "unit": "m/s^2", "precision": 4},
        },
        "fit": fit_result,
        "rows": calc_rows,
        "uncertainty_breakdown": {
            "mean_length": mean_length,
            "mean_period": mean_period,
            "length_source": length_uncertainty,
            "period_source": period_uncertainty,
        },
        "checks": _compute_checks(g_mean, fit_result, g_fit, len(rows)),
    }


def build_local_narrative(normalized: dict, compute_result: dict) -> dict:
    g_result_text = _metric_with_uncertainty_text(compute_result, "g_mean", "g_uncertainty")
    g_fit = _metric_text(compute_result, "g_fit", significant_digits=4)
    g_a_uncertainty = _uncertainty_metric_text(compute_result, "g_a_uncertainty")
    g_uncertainty = _uncertainty_metric_text(compute_result, "g_uncertainty")
    enabled_b_fields = _enabled_b_uncertainty_fields(compute_result)
    fit_r2 = compute_result["fit"].get("r2")
    r2_text = "不可用" if fit_r2 is None else f"{fit_r2:.4f}"
    final_result = f"g = {g_result_text}"
    result_summary = (
        f"本实验根据单摆周期公式对 {len(normalized['rows'])} 组摆长与周期数据进行处理。"
        f"平均法结果为 g = {g_result_text}，线性拟合得到的重力加速度为 {g_fit}，"
        f"拟合优度 R² 为 {r2_text}。"
    )
    error_analysis = (
        "主要误差可能来自摆长读数、周期计时反应误差、摆角过大导致的小角度近似偏差，"
        "以及空气阻力和支点摩擦等非理想因素。建议增加重复测量次数，并尽量保持小摆角释放。"
    )
    if enabled_b_fields:
        b_parts = "，".join(
            f"{field['symbol']} = {_uncertainty_metric_text(compute_result, field['metric_key'])}"
            for field in enabled_b_fields
        )
        uncertainty_summary = (
            f"A 类标准不确定度 u_A(g) = {g_a_uncertainty}；"
            f"B 类分量 {b_parts}；"
            f"最终合成标准不确定度 u_c(g) = {g_uncertainty}。"
        )
    else:
        uncertainty_summary = f"A 类标准不确定度 u_A(g) = {g_a_uncertainty}，最终标准不确定度取 {g_uncertainty}。"
    thinking_answer = None
    if normalized["options"].get("include_thinking"):
        thinking_answer = "若摆角较大，单摆周期会偏离小角度近似公式，通常会使计算得到的 g 出现系统偏差。"
    return {
        "result_summary": result_summary,
        "error_analysis": error_analysis,
        "uncertainty_summary": uncertainty_summary,
        "final_result": final_result,
        "thinking_answer": thinking_answer,
    }


def build_render_context(normalized: dict, compute_result: dict, narrative: dict) -> dict:
    student = normalized["student"]
    report_narrative = _sanitize_report_narrative(
        narrative,
        compute_result,
        fallback=build_local_narrative(normalized, compute_result),
    )
    raw_rows = [
        [row["index"], _fmt(row["length_m"], 4), _fmt(row["period_s"], 4)]
        for row in normalized["rows"]
    ]
    calc_rows = [
        [
            row["index"],
            _fmt(row["period_squared"], 5),
            _fmt(row["g_value"], 5),
        ]
        for row in compute_result["rows"]
    ]
    fit = compute_result["fit"]
    g_result_text = _metric_with_uncertainty_text(compute_result, "g_mean", "g_uncertainty")
    uncertainty_rows = _uncertainty_rows(compute_result)
    enabled_b_fields = _enabled_b_uncertainty_fields(compute_result)
    return {
        "title": f"{normalized['experiment_name']}实验报告",
        "section_options": _section_options(normalized.get("options", {})),
        "student_name": student.get("name") or "未填写",
        "student_id": student.get("student_id") or "未填写",
        "class_name": student.get("class_name") or "未填写",
        "experiment_date": student.get("date") or date.today().isoformat(),
        "experiment_id": normalized["experiment_id"],
        "experiment_name": normalized["experiment_name"],
        "raw_headers": ["序号", "摆长 L / m", "周期 T / s"],
        "raw_rows": raw_rows,
        "calc_headers": ["序号", "T² / s²", "g / (m·s⁻²)"],
        "calc_rows": calc_rows,
        "g_mean": _metric_text(compute_result, "g_mean", significant_digits=4),
        "g_fit": _metric_text(compute_result, "g_fit", significant_digits=4),
        "g_a_uncertainty": _uncertainty_metric_text(compute_result, "g_a_uncertainty"),
        "g_b_length_uncertainty": _uncertainty_metric_text(compute_result, "g_b_length_uncertainty"),
        "g_b_period_uncertainty": _uncertainty_metric_text(compute_result, "g_b_period_uncertainty"),
        "g_b_uncertainty": _uncertainty_metric_text(compute_result, "g_b_uncertainty"),
        "g_uncertainty": _uncertainty_metric_text(compute_result, "g_uncertainty"),
        "final_result": f"g = {g_result_text}",
        "uncertainty_rows": uncertainty_rows,
        "has_b_uncertainty": bool(enabled_b_fields),
        "enabled_b_uncertainty_fields": enabled_b_fields,
        "formula_method_label": enabled_b_fields[0]["method_label"] if enabled_b_fields else "",
        "figures": compute_result.get("figures", []),
        "fit_intercept": _fmt_with_unit(fit.get("intercept"), "s²"),
        "fit_r2": "不可用" if fit.get("r2") is None else f"{fit['r2']:.4f}",
        "result_summary": report_narrative["result_summary"],
        "error_analysis": report_narrative["error_analysis"],
        "uncertainty_summary": report_narrative["uncertainty_summary"],
        "thinking_answer": report_narrative.get("thinking_answer"),
    }


def _enabled_b_uncertainty_fields(compute_result: dict) -> list[dict]:
    fields = []
    specs = [
        {
            "field": "length",
            "label": "摆长",
            "symbol": "u_B(L)",
            "metric_key": "g_b_length_uncertainty",
            "propagation": "按 ∂g/∂L 传播",
        },
        {
            "field": "period",
            "label": "周期",
            "symbol": "u_B(T)",
            "metric_key": "g_b_period_uncertainty",
            "propagation": "按 ∂g/∂T 传播",
        },
    ]
    breakdown = compute_result.get("uncertainty_breakdown", {})
    for spec in specs:
        source = breakdown.get(f"{spec['field']}_source", {})
        if source.get("enabled"):
            fields.append(
                {
                    **spec,
                    "method_label": source.get("method_label") or B_UNCERTAINTY_METHODS["half_division_uniform"]["label"],
                }
            )
    return fields


def _uncertainty_rows(compute_result: dict) -> list[list[str]]:
    rows = [["A 类", _uncertainty_metric_text(compute_result, "g_a_uncertainty"), "样本标准差 / √n"]]
    enabled_b_fields = _enabled_b_uncertainty_fields(compute_result)
    for field in enabled_b_fields:
        rows.append(
            [
                f"B 类({field['label']})",
                _uncertainty_metric_text(compute_result, field["metric_key"]),
                f"{field['method_label']}，{field['propagation']}",
            ]
        )
    if len(enabled_b_fields) > 1:
        rows.append(["B 类合成", _uncertainty_metric_text(compute_result, "g_b_uncertainty"), "各 B 分量矢量和"])
    if enabled_b_fields:
        rows.append(["最终合成", _uncertainty_metric_text(compute_result, "g_uncertainty"), "√(u_A² + Σu_Bi²)"])
    return rows


def _section_options(options: dict) -> dict:
    return {
        "basic_info": options.get("include_basic_info", True),
        "raw_data": options.get("include_raw_appendix", True),
        "data_processing": options.get("include_data_processing", True),
        "computer_plot": options.get("include_computer_plot", True),
        "uncertainty": options.get("include_uncertainty", True),
        "result_summary": options.get("include_result_summary", True),
        "thinking": options.get("include_thinking", False),
    }


def validate_render_context(context: dict, required_fields: list[str]) -> None:
    missing = [field for field in required_fields if field not in context]
    if missing:
        raise WorkflowError(f"渲染上下文缺少字段：{', '.join(missing)}")


def _with_defaults(request: dict, source: str) -> dict:
    student = request.get("student") or {}
    options = {"include_thinking": False, "include_raw_appendix": True}
    options.update(request.get("options") or {})
    return {
        "experiment_id": request.get("experiment_id") or "exp_001",
        "student": {
            "name": student.get("name") or "",
            "student_id": student.get("student_id") or "",
            "class_name": student.get("class_name") or "",
            "date": student.get("date") or student.get("experiment_date") or date.today().isoformat(),
        },
        "options": options,
        "data": request.get("data") or {},
        "source": request.get("source") or source,
        "ocr_meta": request.get("ocr_meta"),
    }


def _read_csv_series(rows: list[dict], candidates: list[str]) -> tuple[list[float], str]:
    headers = rows[0].keys()
    selected = next((name for name in candidates if name in headers), None)
    if not selected:
        raise WorkflowError(f"CSV 缺少字段，候选字段：{', '.join(candidates)}")
    values = [_to_float(row.get(selected), selected) for row in rows]
    unit = selected.rsplit("_", 1)[-1] if "_" in selected else "m"
    if selected == "period":
        unit = "s"
    if selected == "length":
        unit = "m"
    return values, unit


def _extract_series(data: dict, field: str, aliases: list[str]) -> list[float]:
    if field in data:
        value = data[field]
        if isinstance(value, dict):
            unit = value.get("unit")
            values = value.get("values")
        else:
            unit = "m" if field == "length" else "s"
            values = value
        return [_convert_unit(_to_float(item, field), unit, field) for item in values]

    for alias in aliases:
        if alias in data:
            unit = alias.rsplit("_", 1)[-1]
            if alias.endswith("_list") or alias.endswith("_values"):
                unit = "s" if field == "period" else "m"
            return [_convert_unit(_to_float(item, alias), unit, field) for item in data[alias]]
    raise WorkflowError(f"缺少实验数据字段：{field}")


def _convert_unit(value: float, unit: str | None, field: str) -> float:
    if unit is None:
        raise WorkflowError(f"字段 {field} 缺少单位。")
    unit = unit.strip()
    if unit not in UNIT_FACTORS:
        raise WorkflowError(f"字段 {field} 不支持单位 {unit!r}。")
    return value * UNIT_FACTORS[unit]


def _to_float(value: object, field: str) -> float:
    if value is None or value == "":
        raise WorkflowError(f"字段 {field} 存在空值，请人工确认后再生成报告。")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise WorkflowError(f"字段 {field} 的值不是数字：{value!r}") from exc


def _check_range(field: str, value: float, spec: dict, index: int) -> None:
    if not (spec["min"] <= value <= spec["max"]):
        raise WorkflowError(
            f"第 {index} 行 {spec['label']} 超出 demo 合理范围：{value} {spec['base_unit']}，"
            f"期望 {spec['min']}~{spec['max']} {spec['base_unit']}。"
        )


def _normalize_b_uncertainty(data: dict, field: str, base_unit: str) -> dict:
    field_data = data.get(field)
    if not isinstance(field_data, dict):
        return {"enabled": False}
    raw_uncertainty = field_data.get("b_uncertainty") or {}
    if not raw_uncertainty.get("enabled"):
        return {"enabled": False}
    division = raw_uncertainty.get("division")
    if division in (None, ""):
        raise WorkflowError(f"字段 {field} 已启用 B 类不确定度，但没有填写分度值。")
    source_unit = raw_uncertainty.get("unit") or field_data.get("unit") or base_unit
    division_base = _convert_unit(_to_float(division, f"{field}.b_uncertainty.division"), source_unit, field)
    if division_base <= 0:
        raise WorkflowError(f"字段 {field} 的仪器分度值必须大于 0。")
    method = raw_uncertainty.get("method") or "half_division_uniform"
    if method not in B_UNCERTAINTY_METHODS:
        supported = ", ".join(B_UNCERTAINTY_METHODS)
        raise WorkflowError(f"字段 {field} 的 B 类不确定度方法 {method!r} 不支持，可选：{supported}")
    return {
        "enabled": True,
        "division": division_base,
        "unit": base_unit,
        "source_unit": source_unit,
        "method": method,
        "method_label": B_UNCERTAINTY_METHODS[method]["label"],
        "standard": _standard_uncertainty_from_division(division_base, method),
    }


def _standard_uncertainty_from_division(division: float, method: str) -> float:
    if method == "division_uniform":
        return division / math.sqrt(3)
    return division / (2 * math.sqrt(3))


def _b_uncertainty_label(compute_result: dict, field: str) -> str:
    source = compute_result.get("uncertainty_breakdown", {}).get(f"{field}_source", {})
    if not source.get("enabled"):
        return ""
    return source.get("method_label") or B_UNCERTAINTY_METHODS["half_division_uniform"]["label"]


def _linear_fit(x_values: list[float], y_values: list[float]) -> dict:
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    sxx = sum((x - x_mean) ** 2 for x in x_values)
    if sxx == 0:
        return {"slope": 0.0, "intercept": y_mean, "r2": None}
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    predictions = [slope * x + intercept for x in x_values]
    ss_res = sum((y - pred) ** 2 for y, pred in zip(y_values, predictions))
    ss_tot = sum((y - y_mean) ** 2 for y in y_values)
    r2 = None if ss_tot == 0 else 1 - ss_res / ss_tot
    return {"slope": slope, "intercept": intercept, "r2": r2}


def _compute_checks(g_mean: float, fit_result: dict, g_fit: float | None, row_count: int) -> list[dict]:
    checks = []
    if row_count < 5:
        checks.append({"level": "warning", "code": "SMALL_SAMPLE_SIZE", "message": "数据组数少于 5，建议增加重复测量。"})
    if not (8.0 <= g_mean <= 11.0):
        checks.append({"level": "warning", "code": "G_MEAN_OUT_OF_RANGE", "message": "平均法 g 偏离常见地表范围。"})
    if g_fit is None or not (8.0 <= g_fit <= 11.0):
        checks.append({"level": "warning", "code": "G_FIT_OUT_OF_RANGE", "message": "拟合法 g 偏离常见地表范围。"})
    if fit_result.get("r2") is not None and fit_result["r2"] < 0.95:
        checks.append({"level": "warning", "code": "LOW_FIT_R2", "message": "线性拟合 R² 较低，请检查数据。"})
    return checks


def _metric_text(compute_result: dict, key: str, *, significant_digits: int = 5) -> str:
    metric = compute_result["metrics"][key]
    return _fmt_with_unit(metric.get("value"), metric["unit"], significant_digits=significant_digits)


def _uncertainty_metric_text(compute_result: dict, key: str) -> str:
    metric = compute_result["metrics"][key]
    return _fmt_uncertainty_with_unit(metric.get("value"), metric["unit"])


def _metric_with_uncertainty_text(compute_result: dict, value_key: str, uncertainty_key: str) -> str:
    value_metric = compute_result["metrics"][value_key]
    uncertainty_metric = compute_result["metrics"][uncertainty_key]
    value = value_metric.get("value")
    uncertainty = uncertainty_metric.get("value")
    unit = value_metric["unit"]
    if value is None:
        return f"不可用 {unit}"
    if uncertainty is None or uncertainty == 0:
        return f"{_format_significant(float(value), 4)} {unit}"
    uncertainty_text, decimals = _format_uncertainty(float(uncertainty))
    value_text = _format_decimal_place(float(value), decimals)
    return f"({value_text} ± {uncertainty_text}) {unit}"


def _metric_value(compute_result: dict, key: str) -> float:
    metric = compute_result["metrics"][key]
    return float(metric.get("value") or 0.0)


def _fmt_with_unit(value: float | None, unit: str, *, significant_digits: int = 5) -> str:
    if value is None:
        return "不可用"
    return f"{_format_significant(value, significant_digits)} {unit}"


def _fmt_uncertainty_with_unit(value: float | None, unit: str) -> str:
    if value is None:
        return "不可用"
    return f"{_format_uncertainty(value)[0]} {unit}"


def _fmt(value: float, digits: int) -> str:
    return f"{value:.{digits}g}"


def _format_uncertainty(value: float) -> tuple[str, int]:
    abs_value = abs(value)
    if abs_value == 0:
        return "0", 0
    exponent = math.floor(math.log10(abs_value))
    first_digit = int(abs_value / (10**exponent))
    significant_digits = 2 if first_digit in (1, 2) else 1
    decimals = significant_digits - 1 - exponent
    return _format_decimal_place(value, decimals), decimals


def _format_decimal_place(value: float, decimals: int) -> str:
    rounded = round(value, decimals)
    if decimals > 0:
        return f"{rounded:.{decimals}f}"
    if decimals == 0:
        return f"{rounded:.0f}"
    return f"{rounded:.0f}"


def _format_significant(value: float, significant_digits: int) -> str:
    if value == 0:
        return "0"
    return f"{value:.{significant_digits}g}"


def _sanitize_narrative(llm_narrative: dict, fallback: dict, compute_result: dict) -> dict:
    result = {}
    result["result_summary"] = fallback.get("result_summary")
    for key in ["error_analysis", "thinking_answer"]:
        value = llm_narrative.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = _sanitize_report_text(value.strip(), compute_result)
            result[key] = cleaned or fallback.get(key)
        else:
            result[key] = fallback.get(key)
    return result


def _sanitize_report_narrative(narrative: dict, compute_result: dict, fallback: dict | None = None) -> dict:
    result = dict(narrative)
    for key in ["result_summary", "error_analysis", "uncertainty_summary", "thinking_answer"]:
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = _sanitize_report_text(value.strip(), compute_result)
            if cleaned:
                result[key] = cleaned
            elif fallback is not None:
                result[key] = fallback.get(key)
    return result


def _sanitize_report_text(text: str, compute_result: dict) -> str:
    enabled_b_fields = _enabled_b_uncertainty_fields(compute_result)
    sentences = _split_report_sentences(text)
    kept_sentences = []
    for sentence in sentences:
        if _is_internal_uncertainty_note(sentence, has_b_uncertainty=bool(enabled_b_fields)):
            continue
        kept_sentences.append(sentence)
    return _normalize_report_wording("".join(kept_sentences)).strip()


def _normalize_report_wording(text: str) -> str:
    replacements = {
        "系统检查提示": "",
        "系统提示": "",
        "根据锁定计算结果": "根据实验数据计算",
        "输入中": "",
        "设置中": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _split_report_sentences(text: str) -> list[str]:
    sentences = []
    start = 0
    for index, char in enumerate(text):
        if char in "。！？；\n":
            sentences.append(text[start : index + 1])
            start = index + 1
    if start < len(text):
        sentences.append(text[start:])
    return sentences


def _is_internal_uncertainty_note(sentence: str, *, has_b_uncertainty: bool) -> bool:
    compact = sentence.replace(" ", "")
    internal_terms = ["未启用", "没有启用", "未提供", "未勾选", "未设置"]
    if any(term in compact for term in internal_terms):
        return True
    if not has_b_uncertainty and ("B类" in compact or "B型" in compact):
        return True
    if "不确定度" in compact and any(term in compact for term in ["为0", "0.0000", "完全由A类", "未纳入", "未包含", "未计入"]):
        return True
    return False


def _make_run_id(experiment_id: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"{timestamp}_{experiment_id}_{suffix}"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

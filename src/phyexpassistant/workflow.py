from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import json
import uuid

from .docx_writer import write_docx
from .experiments import get_experiment
from .llm_client import LLMClient, LLMError
from .paths import output_root
from .plotting import write_safe_plot
from .settings import Settings


OUTPUT_ROOT = output_root()

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


def generate_report(request: dict, settings: Settings, *, use_llm: bool = True) -> dict:
    request = _with_defaults(request, source=request.get("source", "unknown"))
    experiment = get_experiment(request["experiment_id"])
    original_photo_path = _resolve_original_photo_path(request)
    run_id = _make_run_id(request["experiment_id"])
    run_dir = OUTPUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    _write_json(run_dir / "input.request.json", request)
    normalized = normalize_generic_request(request, experiment)
    _write_json(run_dir / "input.normalized.json", normalized)
    report_content = build_generic_local_narrative(normalized)
    plot_plan = {"need_plot": False, "reason": "LLM 未生成绘图计划。", "safe_spec": {"plots": []}, "warnings": []}
    llm = None

    if use_llm and settings.is_llm_ready:
        try:
            llm = LLMClient(settings)
            llm_report_content = llm.generate_report_content(normalized, experiment, note=request.get("report_generation_note"))
            report_content = _sanitize_generic_narrative(llm_report_content, report_content, normalized)
        except LLMError as exc:
            warnings.append(f"LLM 报告内容生成失败，已使用本地通用模板：{exc}")
        if llm is not None:
            try:
                llm_plot_plan = llm.plan_plots(normalized, experiment, report_content)
                plot_plan = _sanitize_plot_plan(llm_plot_plan)
                warnings.extend(plot_plan.get("warnings") or [])
            except LLMError as exc:
                warnings.append(f"LLM 绘图计划生成失败，已跳过计算机绘图：{exc}")
    elif use_llm:
        warnings.append("LLM 未配置，已使用本地通用模板生成报告文字。")

    if normalized.get("options", {}).get("force_computer_plot") and not use_llm:
        warnings.append("已启用强制绘图，但当前关闭了 LLM，无法生成绘图计划。")
    if normalized.get("options", {}).get("force_computer_plot") and use_llm and not plot_plan.get("need_plot"):
        warnings.append("已启用强制绘图，但模型未生成可用绘图计划。")

    figures = _render_safe_plots(run_dir, normalized, plot_plan, warnings)
    analysis_result = {
        "report_content": report_content,
        "plot_plan": plot_plan,
        "figures": figures,
    }
    _write_json(run_dir / "compute.result.json", analysis_result)
    _write_json(run_dir / "narrative.result.json", report_content)
    _write_json(run_dir / "plot.plan.json", plot_plan)

    render_context = build_generic_render_context(
        normalized,
        report_content,
        figures,
        plot_plan,
        original_photo_path=original_photo_path,
    )
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
        "original_photo_path": original_photo_path,
        "artifacts": {
            "request": str(run_dir / "input.request.json"),
            "normalized_input": str(run_dir / "input.normalized.json"),
            "compute_result": str(run_dir / "compute.result.json"),
            "narrative_result": str(run_dir / "narrative.result.json"),
            "plot_plan": str(run_dir / "plot.plan.json"),
            "render_context": str(run_dir / "render.context.json"),
            "report": str(report_path),
            "figures": [figure["path"] for figure in figures],
        },
        "warnings": warnings,
    }
    _write_json(run_dir / "manifest.json", manifest)
    return {"run_id": run_id, "run_dir": str(run_dir), "report_path": str(report_path), "warnings": warnings}


def normalize_generic_request(request: dict, experiment: dict) -> dict:
    data = request.get("data") or {}
    fields = experiment.get("fields") or {}
    normalized_fields = []
    normalized_data = {}
    row_count = 0

    for field_name, spec in fields.items():
        field_data = data.get(field_name, {})
        if isinstance(field_data, dict):
            unit = field_data.get("unit") or spec.get("base_unit") or ""
            values = field_data.get("values") or []
            b_uncertainty = field_data.get("b_uncertainty") or {"enabled": False}
        elif isinstance(field_data, list):
            unit = spec.get("base_unit") or ""
            values = field_data
            b_uncertainty = {"enabled": False}
        elif field_data not in (None, ""):
            unit = spec.get("base_unit") or ""
            values = [field_data]
            b_uncertainty = {"enabled": False}
        else:
            unit = spec.get("base_unit") or ""
            values = []
            b_uncertainty = {"enabled": False}

        clean_values = [None if value in (None, "") else value for value in values]
        row_count = max(row_count, len(clean_values))
        normalized_field = {
            "field": field_name,
            "label": spec.get("label") or field_name,
            "unit": unit,
            "base_unit": spec.get("base_unit") or unit,
            "accepted_units": spec.get("accepted_units") or [],
            "values": clean_values,
            "b_uncertainty": b_uncertainty,
        }
        normalized_fields.append(normalized_field)
        normalized_data[field_name] = normalized_field

    raw_headers = ["序号"] + [_generic_header(field) for field in normalized_fields]
    raw_rows = []
    for row_index in range(row_count):
        row = [row_index + 1]
        for field in normalized_fields:
            values = field["values"]
            row.append(_format_generic_value(values[row_index]) if row_index < len(values) else "")
        raw_rows.append(row)

    student = request["student"]
    return {
        "report_mode": experiment.get("report_mode") or "llm_generic",
        "experiment_id": request["experiment_id"],
        "experiment_name": experiment["name"],
        "experiment_description": experiment.get("description") or "",
        "student": student,
        "options": request["options"],
        "data": normalized_data,
        "fields": normalized_fields,
        "raw_headers": raw_headers,
        "raw_rows": raw_rows,
        "ocr_meta": request.get("ocr_meta") or {},
    }


def build_generic_local_narrative(normalized: dict) -> dict:
    experiment_name = normalized["experiment_name"]
    field_names = "、".join(field["label"] for field in normalized["fields"])
    return {
        "generic_formula_lines": [
            f"根据《{experiment_name}》实验原理，对记录表中的 {field_names} 等数据进行整理。",
            "结合实验装置的平衡条件、仪器读数和重复测量结果，对待测物理量进行计算和比较。",
        ],
        "generic_processing_summary": "根据实验记录表整理各测量量，数据处理时应结合实验原理、仪器校准信息和有效数字规则。",
        "generic_result_headers": ["项目", "内容"],
        "generic_result_rows": [["数据组数", str(len(normalized["raw_rows"]))], ["记录字段", field_names]],
        "uncertainty_summary": "不确定度分析应结合实验仪器分度值、重复测量情况和实验原理进行评定。",
        "final_result": "实验结果见数据处理与结果总结。",
        "result_summary": f"本实验完成了 {experiment_name} 的数据记录与整理，主要记录量包括 {field_names}。",
        "error_analysis": "主要误差来源需结合仪器读数、连接与调零状态、环境条件以及重复测量离散性进行分析。",
        "thinking_answer": None,
    }


def build_generic_render_context(
    normalized: dict,
    report_content: dict,
    figures: list[dict],
    plot_plan: dict,
    *,
    original_photo_path: str | None = None,
) -> dict:
    student = normalized["student"]
    return {
        "report_mode": "llm",
        "title": f"{normalized['experiment_name']}实验报告",
        "section_options": _section_options(normalized.get("options", {})),
        "student_name": student.get("name") or "未填写",
        "student_id": student.get("student_id") or "未填写",
        "class_name": student.get("class_name") or "未填写",
        "experiment_date": student.get("date") or date.today().isoformat(),
        "experiment_id": normalized["experiment_id"],
        "experiment_name": normalized["experiment_name"],
        "experiment_description": normalized.get("experiment_description") or "",
        "original_photo_path": original_photo_path,
        "raw_headers": normalized["raw_headers"],
        "raw_rows": normalized["raw_rows"],
        "generic_formula_lines": report_content.get("generic_formula_lines") or [],
        "generic_processing_summary": report_content.get("generic_processing_summary") or "",
        "generic_result_headers": report_content.get("generic_result_headers") or ["项目", "内容"],
        "generic_result_rows": report_content.get("generic_result_rows") or [],
        "uncertainty_summary": report_content.get("uncertainty_summary") or "",
        "final_result": report_content.get("final_result") or "",
        "result_summary": report_content.get("result_summary") or "",
        "error_analysis": report_content.get("error_analysis") or "",
        "thinking_answer": report_content.get("thinking_answer"),
        "need_plot": bool(plot_plan.get("need_plot")),
        "plot_reason": plot_plan.get("reason") or "",
        "force_computer_plot": bool(normalized.get("options", {}).get("force_computer_plot")),
        "forced_plot_count": int(normalized.get("options", {}).get("forced_plot_count") or 1),
        "figures": figures,
    }


def _sanitize_plot_plan(plot_plan: dict) -> dict:
    safe_spec = plot_plan.get("safe_spec") if isinstance(plot_plan, dict) else {}
    plots = []
    for plot in (safe_spec or {}).get("plots") or []:
        if not isinstance(plot, dict):
            continue
        plot_type = str(plot.get("plot_type") or "").strip()
        if plot_type not in {"scatter", "line", "scatter_with_linear_fit", "bar"}:
            continue
        plots.append(
            {
                "key": str(plot.get("key") or f"plot_{len(plots) + 1}"),
                "title": str(plot.get("title") or "计算机绘图"),
                "caption": str(plot.get("caption") or plot.get("title") or "计算机绘图"),
                "description": str(plot.get("description") or ""),
                "position": str(plot.get("position") or "after_calculation_results"),
                "plot_type": plot_type,
                "x": plot.get("x") or {},
                "y": plot.get("y") or {},
                "fit": plot.get("fit") or {"enabled": False},
            }
        )
    need_plot = bool(plot_plan.get("need_plot")) and bool(plots)
    return {
        "need_plot": need_plot,
        "reason": str(plot_plan.get("reason") or ""),
        "safe_spec": {"plots": plots},
        "warnings": [str(item) for item in (plot_plan.get("warnings") or []) if str(item).strip()],
    }


def _render_safe_plots(run_dir: Path, normalized: dict, plot_plan: dict, warnings: list[str]) -> list[dict]:
    figures: list[dict] = []
    if not plot_plan.get("need_plot"):
        return figures
    safe_spec = plot_plan.get("safe_spec") or {}
    for index, plot_spec in enumerate(safe_spec.get("plots") or [], start=1):
        key = str(plot_spec.get("key") or f"plot_{index}")
        output_path = run_dir / "figures" / f"{key}.png"
        try:
            figure = write_safe_plot(output_path, plot_spec, normalized)
            if not figure.get("caption"):
                figure["caption"] = plot_spec.get("caption") or plot_spec.get("title") or "计算机绘图"
            figures.append(figure)
        except Exception as exc:
            warnings.append(f"safe_spec 绘图 {key} 失败，已跳过：{exc}")
    return figures


def _string_list(value: object, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return cleaned or fallback


def _table_rows(value: object) -> list[list[str]]:
    rows = []
    if not isinstance(value, list):
        return rows
    for row in value:
        if isinstance(row, list):
            rows.append([str(item) for item in row])
        else:
            rows.append([str(row)])
    return rows


def _generic_header(field: dict) -> str:
    unit = field.get("unit") or ""
    return f"{field['label']} / {unit}" if unit else field["label"]


def _format_generic_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return _format_significant(value, 6)
    return str(value)


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
    options = {
        "include_thinking": False,
        "include_raw_appendix": True,
        "force_computer_plot": False,
        "forced_plot_count": 1,
    }
    options.update(request.get("options") or {})
    options["force_computer_plot"] = bool(options.get("force_computer_plot"))
    try:
        forced_plot_count = int(options.get("forced_plot_count") or 1)
    except (TypeError, ValueError):
        forced_plot_count = 1
    options["forced_plot_count"] = max(1, min(3, forced_plot_count))
    normalized_request = {
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
        "original_photo_path": request.get("original_photo_path") or request.get("manual_report_photo_path"),
    }
    report_generation_note = str(request.get("report_generation_note") or "").strip()
    if report_generation_note:
        normalized_request["report_generation_note"] = report_generation_note
    return normalized_request


def _format_significant(value: float, significant_digits: int) -> str:
    if value == 0:
        return "0"
    return f"{value:.{significant_digits}g}"


def _sanitize_generic_narrative(llm_narrative: dict, fallback: dict, normalized: dict) -> dict:
    has_b_uncertainty = any(
        isinstance(field, dict) and (field.get("b_uncertainty") or {}).get("enabled")
        for field in (normalized.get("fields") or [])
    )
    result = {}
    result["generic_formula_lines"] = _string_list(llm_narrative.get("generic_formula_lines"), fallback.get("generic_formula_lines") or [])
    for key in ["generic_processing_summary", "uncertainty_summary", "final_result", "result_summary", "error_analysis", "thinking_answer"]:
        value = llm_narrative.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = _sanitize_report_text(value.strip(), has_b_uncertainty=has_b_uncertainty)
            result[key] = cleaned or fallback.get(key)
        else:
            result[key] = fallback.get(key)
    headers = llm_narrative.get("generic_result_headers")
    rows = llm_narrative.get("generic_result_rows")
    result["generic_result_headers"] = [str(item) for item in headers] if isinstance(headers, list) and headers else fallback.get("generic_result_headers")
    result["generic_result_rows"] = _table_rows(rows) if isinstance(rows, list) and rows else fallback.get("generic_result_rows")
    return result


def _sanitize_report_text(text: str, *, has_b_uncertainty: bool) -> str:
    sentences = _split_report_sentences(text)
    kept_sentences = []
    for sentence in sentences:
        if _is_internal_uncertainty_note(sentence, has_b_uncertainty=has_b_uncertainty):
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


def _resolve_original_photo_path(request: dict) -> str | None:
    original_photo_path = request.get("original_photo_path") or request.get("manual_report_photo_path")
    if original_photo_path:
        return str(original_photo_path)

    source = request.get("source")
    if isinstance(source, str):
        suffix = Path(source).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}:
            return source
    return None

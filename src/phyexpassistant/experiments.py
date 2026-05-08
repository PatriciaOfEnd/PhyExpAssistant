from __future__ import annotations

import json
import re
from copy import deepcopy
from functools import lru_cache
from numbers import Real
from pathlib import Path

from .paths import package_path


RENDER_CONTRACT = [
    "report_mode",
    "student_name",
    "student_id",
    "class_name",
    "experiment_name",
    "experiment_date",
    "raw_headers",
    "raw_rows",
    "generic_formula_lines",
    "generic_processing_summary",
    "generic_result_headers",
    "generic_result_rows",
    "uncertainty_summary",
    "final_result",
    "result_summary",
    "error_analysis",
    "figures",
]


@lru_cache(maxsize=1)
def _load_catalog() -> dict:
    data = normalize_experiment_catalog(read_experiment_catalog())
    experiments = data.get("experiments") or []
    catalog: dict[str, dict] = {}
    for experiment in experiments:
        experiment_id = experiment.get("id")
        catalog[str(experiment_id)] = experiment
    if not catalog:
        raise ValueError("实验模板目录中没有可用实验。")
    return catalog


def experiments_dir() -> Path:
    return package_path("resources", "experiments")


def experiments_path() -> Path:
    return package_path("resources", "experiments.json")


def experiment_template_files() -> list[Path]:
    directory = experiments_dir()
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def experiment_template_path(experiment_id: str) -> Path:
    return experiments_dir() / f"{_safe_template_filename(experiment_id)}.json"


def read_experiment_catalog() -> dict:
    template_files = experiment_template_files()
    if template_files:
        experiments = [_read_experiment_file(path) for path in template_files]
        return {"experiments": experiments}

    legacy_path = experiments_path()
    if legacy_path.exists():
        return json.loads(legacy_path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"实验模板目录不存在或为空：{experiments_dir()}")


def experiment_catalog_text(catalog: dict | None = None) -> str:
    catalog = read_experiment_catalog() if catalog is None else catalog
    return json.dumps(catalog, ensure_ascii=False, indent=2)


def save_experiment_catalog(catalog: dict) -> None:
    normalized_catalog = normalize_experiment_catalog(catalog)
    directory = experiments_dir()
    directory.mkdir(parents=True, exist_ok=True)
    written_paths = set()
    for experiment in normalized_catalog["experiments"]:
        path = experiment_template_path(experiment["id"])
        path.write_text(json.dumps(experiment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written_paths.add(path.resolve())
    for path in experiment_template_files():
        if path.resolve() not in written_paths:
            path.unlink()
    legacy_path = experiments_path()
    if legacy_path.exists():
        legacy_path.unlink()
    _load_catalog.cache_clear()


def reload_experiment_catalog() -> None:
    _load_catalog.cache_clear()


def _read_experiment_file(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "experiment" in payload:
        payload = payload["experiment"]
    if isinstance(payload, dict) and "experiments" in payload:
        raise ValueError(f"单个模板文件不能包含 experiments 列表：{path}")
    return normalize_experiment_definition(payload)


def _safe_template_filename(experiment_id: object) -> str:
    text = str(experiment_id or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    if not text:
        raise ValueError("实验模板 id 不能为空，无法生成文件名。")
    return text


def normalize_template_payload(payload: object, *, base_catalog: dict | None = None) -> dict:
    if isinstance(payload, dict):
        for wrapper_key in ("template", "experiment_template", "generated_template", "result"):
            wrapped_payload = payload.get(wrapper_key)
            if isinstance(wrapped_payload, dict):
                return normalize_template_payload(wrapped_payload, base_catalog=base_catalog)

    if isinstance(payload, dict) and isinstance(payload.get("experiments"), list):
        imported_catalog = normalize_experiment_catalog(payload)
        if base_catalog is None:
            return imported_catalog
        merged_catalog = normalize_experiment_catalog(base_catalog)
        for experiment in imported_catalog["experiments"]:
            merged_catalog = upsert_experiment(merged_catalog, experiment)
        return merged_catalog

    if isinstance(payload, dict) and "experiment" in payload:
        return upsert_experiment(base_catalog or read_experiment_catalog(), payload["experiment"])

    if isinstance(payload, dict) and "id" in payload and "name" in payload:
        return upsert_experiment(base_catalog or read_experiment_catalog(), payload)

    raise ValueError("模板 JSON 必须是 experiments.json 格式、单个实验模板对象，或包含 experiment 字段的对象。")


def normalize_generated_template_payload(payload: object, *, base_catalog: dict | None = None) -> dict:
    experiment = _single_experiment_payload(payload)
    _validate_generated_template_shape(experiment)
    normalized_experiment = normalize_experiment_definition(experiment)
    normalized_experiment.pop("render_contract", None)
    _validate_generated_template_semantics(normalized_experiment)
    return upsert_experiment(base_catalog or read_experiment_catalog(), normalized_experiment)


def _single_experiment_payload(payload: object) -> dict:
    if isinstance(payload, dict):
        for wrapper_key in ("template", "experiment_template", "generated_template", "result", "experiment"):
            wrapped_payload = payload.get(wrapper_key)
            if isinstance(wrapped_payload, dict):
                return _single_experiment_payload(wrapped_payload)
        if isinstance(payload.get("experiments"), list):
            raise ValueError("LLM 生成模板只能返回单个实验对象，不能返回 experiments 数组。")
        if "id" in payload and "name" in payload:
            return payload
    raise ValueError("LLM 生成模板必须是单个实验模板 JSON 对象。")


def _validate_generated_template_semantics(experiment: dict) -> None:
    forbidden_terms = ("uncertainty", "不确定度", "误差", "标准差", "standard_deviation", "std_dev")
    search_items = [
        str(experiment.get("id", "")),
        str(experiment.get("name", "")),
        str(experiment.get("description", "")),
        *[str(item) for item in experiment.get("formula_hints") or []],
        *[str(item) for item in experiment.get("table_hints") or []],
    ]
    for field_name, field_meta in (experiment.get("fields") or {}).items():
        search_items.append(str(field_name))
        if isinstance(field_meta, dict):
            search_items.append(str(field_meta.get("label", "")))
    for item in search_items:
        lowered = item.lower()
        for term in forbidden_terms:
            if term.lower() in lowered:
                raise ValueError("LLM 生成的模板包含不确定度/误差相关字段或描述，请删除后重试。")


def _validate_generated_template_shape(experiment: dict) -> None:
    allowed_top_level = {"id", "name", "category", "description", "report_mode", "fields", "formula_hints", "table_hints"}
    extra_keys = set(experiment) - allowed_top_level
    if extra_keys:
        raise ValueError(f"LLM 生成的模板包含不允许的顶层字段：{', '.join(sorted(extra_keys))}")
    fields = experiment.get("fields")
    if isinstance(fields, dict):
        allowed_field_keys = {"label", "base_unit", "accepted_units", "min", "max"}
        for field_name, field_meta in fields.items():
            if isinstance(field_meta, dict):
                extra_field_keys = set(field_meta) - allowed_field_keys
                if extra_field_keys:
                    raise ValueError(f"LLM 生成的模板字段 {field_name} 包含不允许的属性：{', '.join(sorted(extra_field_keys))}")


def upsert_experiment(catalog: dict, experiment: object) -> dict:
    normalized_catalog = normalize_experiment_catalog(catalog)
    normalized_experiment = normalize_experiment_definition(experiment)
    experiments = normalized_catalog["experiments"]
    for index, existing in enumerate(experiments):
        if existing.get("id") == normalized_experiment["id"]:
            experiments[index] = normalized_experiment
            validate_experiment_catalog(normalized_catalog)
            return normalized_catalog
    experiments.append(normalized_experiment)
    validate_experiment_catalog(normalized_catalog)
    return normalized_catalog


def normalize_experiment_catalog(catalog: object) -> dict:
    if not isinstance(catalog, dict):
        raise ValueError("experiments.json 顶层必须是 JSON 对象。")
    experiments = catalog.get("experiments")
    if not isinstance(experiments, list):
        raise ValueError("experiments.json 必须包含 experiments 列表。")
    normalized_catalog = deepcopy(catalog)
    normalized_catalog["experiments"] = [normalize_experiment_definition(experiment, index=index) for index, experiment in enumerate(experiments)]
    validate_experiment_catalog(normalized_catalog)
    return normalized_catalog


def validate_experiment_catalog(catalog: object) -> None:
    if not isinstance(catalog, dict):
        raise ValueError("experiments.json 顶层必须是 JSON 对象。")
    experiments = catalog.get("experiments")
    if not isinstance(experiments, list):
        raise ValueError("experiments.json 必须包含 experiments 列表。")
    if not experiments:
        raise ValueError("experiments 列表至少需要一个实验模板。")

    seen_ids: set[str] = set()
    for index, experiment in enumerate(experiments):
        normalized = normalize_experiment_definition(experiment, index=index)
        experiment_id = normalized["id"]
        if experiment_id in seen_ids:
            raise ValueError(f"experiments[{index}].id 重复：{experiment_id}")
        seen_ids.add(experiment_id)


def normalize_experiment_definition(experiment: object, *, index: int | None = None) -> dict:
    prefix = f"experiments[{index}]" if index is not None else "experiment"
    if not isinstance(experiment, dict):
        raise ValueError(f"{prefix} 必须是 JSON 对象。")

    normalized = deepcopy(experiment)
    normalized["id"] = _required_string(experiment.get("id"), f"{prefix}.id")
    normalized["name"] = _required_string(experiment.get("name"), f"{prefix}.name")
    normalized["category"] = _optional_string(experiment.get("category"), f"{prefix}.category", default="custom")
    normalized["description"] = _optional_string(experiment.get("description"), f"{prefix}.description", default="")
    normalized["report_mode"] = _optional_string(experiment.get("report_mode"), f"{prefix}.report_mode", default="llm")
    normalized["fields"] = _normalize_fields(experiment.get("fields"), prefix)

    for list_key in ("formula_hints", "table_hints"):
        if list_key in experiment and experiment[list_key] is not None:
            if not isinstance(experiment[list_key], list) or not all(isinstance(item, str) and item.strip() for item in experiment[list_key]):
                raise ValueError(f"{prefix}.{list_key} 必须是非空字符串列表。")
            normalized[list_key] = [item.strip() for item in experiment[list_key]]

    render_contract = experiment.get("render_contract") or RENDER_CONTRACT
    if not isinstance(render_contract, list) or not all(isinstance(item, str) and item.strip() for item in render_contract):
        raise ValueError(f"{prefix}.render_contract 必须是非空字符串列表。")
    normalized["render_contract"] = [item.strip() for item in render_contract]
    return normalized


def _normalize_fields(fields: object, prefix: str) -> dict:
    if not isinstance(fields, dict):
        raise ValueError(f"{prefix}.fields 必须是 JSON 对象。")
    if not fields:
        raise ValueError(f"{prefix}.fields 至少需要一个数据字段。")

    normalized_fields = {}
    for field_name, field_meta in fields.items():
        field_key = _required_string(field_name, f"{prefix}.fields.<field>")
        if not isinstance(field_meta, dict):
            raise ValueError(f"{prefix}.fields.{field_key} 必须是 JSON 对象。")
        field_copy = deepcopy(field_meta)
        field_copy["label"] = _optional_string(field_meta.get("label"), f"{prefix}.fields.{field_key}.label", default=field_key)
        field_copy["base_unit"] = _optional_string(field_meta.get("base_unit"), f"{prefix}.fields.{field_key}.base_unit", default="")
        accepted_units = field_meta.get("accepted_units")
        if accepted_units is None:
            accepted_units = [field_copy["base_unit"]] if field_copy["base_unit"] else []
        if not isinstance(accepted_units, list) or not all(isinstance(unit, str) for unit in accepted_units):
            raise ValueError(f"{prefix}.fields.{field_key}.accepted_units 必须是字符串列表。")
        field_copy["accepted_units"] = [unit.strip() for unit in accepted_units if unit.strip()]
        if field_copy["base_unit"] and field_copy["base_unit"] not in field_copy["accepted_units"]:
            field_copy["accepted_units"].insert(0, field_copy["base_unit"])
        if not field_copy["accepted_units"]:
            raise ValueError(f"{prefix}.fields.{field_key}.accepted_units 至少需要一个单位；无量纲请使用 ratio。")
        for bound_key in ("min", "max"):
            if bound_key in field_meta and field_meta[bound_key] is not None and (
                isinstance(field_meta[bound_key], bool) or not isinstance(field_meta[bound_key], Real)
            ):
                raise ValueError(f"{prefix}.fields.{field_key}.{bound_key} 必须是数字。")
        normalized_fields[field_key] = field_copy
    return normalized_fields


def _required_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} 必须是非空字符串。")
    return value.strip()


def _optional_string(value: object, path: str, *, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{path} 必须是字符串。")
    return value.strip()


def list_experiments() -> list[dict]:
    return list(_load_catalog().values())


def get_experiment(experiment_id: str) -> dict:
    catalog = _load_catalog()
    try:
        return catalog[experiment_id]
    except KeyError as exc:
        supported = ", ".join(f"{exp['name']}({exp['id']})" for exp in catalog.values())
        raise ValueError(f"暂不支持实验 {experiment_id!r}，当前支持：{supported}") from exc


def get_experiment_by_name(experiment_name: str) -> dict:
    for experiment in _load_catalog().values():
        if experiment.get("name") == experiment_name:
            return experiment
    supported = ", ".join(exp["name"] for exp in _load_catalog().values())
    raise ValueError(f"暂不支持实验 {experiment_name!r}，当前支持：{supported}")

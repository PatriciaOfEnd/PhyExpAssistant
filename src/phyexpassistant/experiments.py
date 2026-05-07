from __future__ import annotations

import json
from functools import lru_cache

from .paths import package_path


@lru_cache(maxsize=1)
def _load_catalog() -> dict:
    path = package_path("resources", "experiments.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    experiments = data.get("experiments") or []
    if not isinstance(experiments, list):
        raise ValueError("experiments.json 格式错误：experiments 必须是列表。")
    catalog: dict[str, dict] = {}
    for experiment in experiments:
        if not isinstance(experiment, dict):
            continue
        experiment_id = experiment.get("id")
        experiment_name = experiment.get("name")
        if not experiment_id or not experiment_name:
            continue
        catalog[str(experiment_id)] = experiment
    if not catalog:
        raise ValueError("experiments.json 中没有可用实验。")
    return catalog


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

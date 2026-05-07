from __future__ import annotations


EXPERIMENTS = {
    "exp_001": {
        "id": "exp_001",
        "name": "单摆测重力加速度",
        "category": "mechanics",
        "description": "根据摆长 L 与周期 T 计算重力加速度 g，并给出线性拟合结果。",
        "fields": {
            "length": {
                "label": "摆长",
                "base_unit": "m",
                "accepted_units": ["m", "cm", "mm"],
                "min": 0.05,
                "max": 5.0,
            },
            "period": {
                "label": "周期",
                "base_unit": "s",
                "accepted_units": ["s", "ms"],
                "min": 0.1,
                "max": 20.0,
            },
        },
        "render_contract": [
            "student_name",
            "student_id",
            "class_name",
            "experiment_name",
            "experiment_date",
            "raw_rows",
            "calc_rows",
            "g_mean",
            "g_fit",
            "g_a_uncertainty",
            "g_b_length_uncertainty",
            "g_b_period_uncertainty",
            "g_b_uncertainty",
            "g_uncertainty",
            "uncertainty_rows",
            "uncertainty_summary",
            "final_result",
            "figures",
            "result_summary",
            "error_analysis",
        ],
    }
}


def list_experiments() -> list[dict]:
    return list(EXPERIMENTS.values())


def get_experiment(experiment_id: str) -> dict:
    try:
        return EXPERIMENTS[experiment_id]
    except KeyError as exc:
        supported = ", ".join(EXPERIMENTS)
        raise ValueError(f"暂不支持实验 {experiment_id!r}，当前支持：{supported}") from exc

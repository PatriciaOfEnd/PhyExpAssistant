from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import json
import os
import sys

from .experiments import get_experiment, list_experiments
from .llm_client import LLMClient, LLMError
from .paths import resolve_input_path
from .settings import Settings, load_settings, save_settings
from .workflow import (
    B_UNCERTAINTY_METHODS,
    WorkflowError,
    generate_report,
)


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _clear_screen() -> None:
    if not sys.stdout.isatty():
        return
    os.system("cls" if os.name == "nt" else "clear")


def _pause_before_menu() -> None:
    if sys.stdin.isatty():
        input("\n按 Enter 返回菜单...")


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="PhyExpAssistant demo")
    parser.add_argument("--ui", action="store_true", help="启动 PySide6 图形界面")
    parser.add_argument("--no-llm", action="store_true", help="手动录入生成报告时不调用 LLM；手写识别仍需 LLM API")
    args = parser.parse_args(argv)

    if args.ui:
        from .ui import launch_ui

        return launch_ui(argv or sys.argv[:1])

    settings = load_settings()
    return _interactive_loop(settings, use_llm=not args.no_llm)


def _interactive_loop(settings: Settings, *, use_llm: bool = True) -> int:
    while True:
        _clear_screen()
        print("\n=== PhyExpAssistant Demo ===")
        print(f"LLM Base URL: {settings.base_url}")
        print(f"LLM Model: {settings.model}")
        print(f"API Key: {settings.masked_api_key}")
        print("1. 设置 API Key / Model")
        print("2. 生成报告：手动录入")
        print("3. 生成报告：手写图片（LLM OCR demo）")
        print("4. 查看支持的实验")
        print("0. 退出")
        choice = input("请选择：").strip()

        try:
            if choice == "1":
                settings = _settings_screen(settings)
            elif choice == "2":
                request = _manual_input_request(_prompt_experiment_id())
                _run_request(request, settings, use_llm=use_llm)
            elif choice == "3":
                request = _ocr_input_request(settings, _prompt_experiment_id())
                if request:
                    _run_request(request, settings, use_llm=use_llm)
            elif choice == "4":
                _print_experiments()
            elif choice == "0":
                return 0
            else:
                print("无效选项，请重新输入。")
        except (WorkflowError, LLMError, FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
            print(f"\n[错误] {exc}")
        _pause_before_menu()


def _settings_screen(settings: Settings) -> Settings:
    print("\n--- LLM 设置 ---")
    print("提示：API Key 会保存到本地项目目录下的 .phyexpassistant/settings.json，该目录已加入 .gitignore。")
    base_url = input(f"Base URL [{settings.base_url}]：").strip()
    model = input(f"Model [{settings.model}]：").strip()
    api_key = input(f"API Key [{settings.masked_api_key}]：").strip()
    timeout = input(f"Timeout seconds [{settings.timeout_seconds}]：").strip()

    if base_url:
        settings.base_url = base_url
    if model:
        settings.model = model
    if api_key:
        settings.api_key = api_key
    if timeout:
        settings.timeout_seconds = int(timeout)
    save_settings(settings)
    print("设置已保存。")
    return settings


def _prompt_student() -> dict:
    print("\n--- 学生信息 ---")
    return {
        "name": input("姓名：").strip(),
        "student_id": input("学号：").strip(),
        "class_name": input("班级：").strip(),
        "date": input(f"实验日期 [{date.today().isoformat()}]：").strip() or date.today().isoformat(),
    }


def _prompt_options() -> dict:
    print("\n--- 输出选项 ---")
    return {
        "include_thinking": _yes_no("包含思考题？", default=False),
        "include_raw_appendix": True,
    }


def _manual_input_request(experiment_id: str) -> dict:
    student = _prompt_student()
    options = _prompt_options()
    experiment = get_experiment(experiment_id)
    print(f"\n--- {experiment['name']}实验数据 ---")
    data = {}
    for field_name, spec in (experiment.get("fields") or {}).items():
        label = spec.get("label") or field_name
        accepted_units = spec.get("accepted_units") or [spec.get("base_unit") or ""]
        default_unit = spec.get("base_unit") or accepted_units[0]
        units_text = "/".join(accepted_units)
        unit = input(f"{label}单位 {units_text} [{default_unit}]：").strip() or default_unit
        values = _parse_number_list(input(f"{label}列表，用逗号分隔："))
        field_data = {"unit": unit, "values": values}
        uncertainty = _prompt_b_uncertainty(label, unit)
        if uncertainty:
            field_data["b_uncertainty"] = uncertainty
        data[field_name] = field_data
    return {
        "experiment_id": experiment_id,
        "student": student,
        "options": options,
        "data": data,
        "source": "manual",
    }


def _ocr_input_request(settings: Settings, experiment_id: str) -> dict | None:
    if not settings.is_llm_ready:
        print("请先进入菜单 1 设置 API Key、Base URL 和 Model。")
        return None
    image_path = _prompt_path("手写数据图片路径：")
    print("正在调用 LLM 识别手写数据，请稍候...")
    request = LLMClient(settings).extract_handwritten_data(image_path, experiment_id)
    _apply_experiment(request, experiment_id)
    request.setdefault("source", str(image_path))
    print("\n--- 识别结果草稿 ---")
    print(json.dumps(request, ensure_ascii=False, indent=2))
    if not _yes_no("是否确认使用该识别结果生成报告？", default=False):
        print("已取消。你可以改用手动录入或重新识别。")
        return None

    student = request.get("student") or {}
    if not all([student.get("name"), student.get("student_id"), student.get("class_name")]):
        print("识别结果缺少学生信息，请手动补充。")
        request["student"] = _prompt_student()
    request.setdefault("options", _prompt_options())
    return request


def _run_request(request: dict, settings: Settings, *, use_llm: bool = True) -> int:
    result = generate_report(request, settings, use_llm=use_llm)
    print("\n生成完成：")
    print(f"- Run ID: {result['run_id']}")
    print(f"- 输出目录: {result['run_dir']}")
    print(f"- 报告文件: {result['report_path']}")
    for warning in result["warnings"]:
        print(f"- 警告: {warning}")
    return 0


def _print_experiments() -> None:
    print("\n当前 demo 支持：")
    for index, experiment in enumerate(list_experiments(), start=1):
        print(f"{index}. {experiment['name']}（{experiment['description']}）")


def _prompt_experiment_id() -> str:
    experiments = list_experiments()
    print("\n--- 选择实验 ---")
    for index, experiment in enumerate(experiments, start=1):
        print(f"{index}. {experiment['name']}")
    choice = input("请选择实验 [1]：").strip()
    if not choice:
        return experiments[0]["id"]
    selected_index = int(choice)
    if selected_index < 1 or selected_index > len(experiments):
        raise ValueError("实验序号超出范围。")
    return experiments[selected_index - 1]["id"]


def _apply_experiment(request: dict, experiment_id: str) -> dict:
    request["experiment_id"] = experiment_id
    return request


def _parse_number_list(text: str) -> list[float]:
    values = []
    for item in text.replace("，", ",").split(","):
        item = item.strip()
        if item:
            values.append(float(item))
    return values


def _prompt_b_uncertainty(label: str, unit: str) -> dict | None:
    if not _yes_no(f"{label}是否计算 B 类不确定度？", default=False):
        return None
    division = float(input(f"{label}仪器分度值 / {unit}：").strip())
    if division <= 0:
        raise ValueError(f"{label}仪器分度值必须大于 0。")
    print("B 类计算方法：")
    print(f"1. {B_UNCERTAINTY_METHODS['half_division_uniform']['label']}（默认）")
    print(f"2. {B_UNCERTAINTY_METHODS['division_uniform']['label']}")
    method_choice = input("请选择 [1/2]：").strip()
    method = "division_uniform" if method_choice == "2" else "half_division_uniform"
    return {"enabled": True, "division": division, "unit": unit, "method": method}


def _prompt_path(prompt: str) -> Path:
    raw_path = input(prompt).strip().strip('"').strip("'")
    return resolve_input_path(raw_path)


def _yes_no(question: str, *, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{question} {suffix}：").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "是", "1"}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

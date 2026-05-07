from __future__ import annotations

from pathlib import Path
import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request

from .experiments import get_experiment
from .paths import package_path
from .settings import Settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings):
        if not settings.is_llm_ready:
            raise LLMError("请先在交互界面设置 API Key、Base URL 和 Model。")
        self.settings = settings

    def extract_handwritten_data(self, image_path: Path, experiment_id: str, note: str | None = None) -> dict:
        image_path = image_path.expanduser().resolve()
        if not image_path.exists():
            raise LLMError(f"图片不存在：{image_path}")

        experiment = get_experiment(experiment_id)
        experiment_name = experiment.get("name") or experiment_id
        experiment_description = experiment.get("description") or ""
        experiment_label = f"{experiment_name}（{experiment_description}）" if experiment_description else experiment_name
        target_template = _build_ocr_target_template(experiment_id, experiment)
        field_specs = [
            {
                "field": field_name,
                "label": field_meta.get("label") or field_name,
                "base_unit": field_meta.get("base_unit") or "",
                "accepted_units": field_meta.get("accepted_units") or [],
            }
            for field_name, field_meta in (experiment.get("fields") or {}).items()
        ]

        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        data_url = f"data:{mime_type};base64,{image_b64}"
        field_specs_json = json.dumps(field_specs, ensure_ascii=False, indent=2)
        target_json = json.dumps(target_template, ensure_ascii=False, indent=2)
        note_text = str(note or "").strip()

        system_prompt = (
            "你是物理实验数据录入助手。请从手写实验数据图片中识别实验数据，"
            "只输出 JSON，不要输出 Markdown。不要猜测缺失值；不确定的字段用 null，"
            "并在 warnings 中说明。数字必须保留原始识别字符串 raw 和 confidence。"
        )
        user_text = f"""
请识别图片中的实验数据，并整理成如下 JSON。当前 demo 选择的实验模板为：{experiment_label}，后台 experiment_id={experiment_id}。

用户备注：
{note_text if note_text else '无'}

备注仅用于辅助识别与约束输出风格，不要把备注原文写入 JSON 结果。

字段说明：
{field_specs_json}

目标 JSON：
{target_json}

要求：
1. data 里的键必须严格使用字段说明中的 field 名称。
2. unit 优先使用图片中出现的单位；若图片没有明确单位，则使用 base_unit。
3. values 中只放数字或 null，不要放带单位的字符串。
4. 无法确认的字段用 null，并在 ocr_meta.warnings 中说明。
5. 若某字段存在多个测量值，请按图片中的顺序写入 values。
""".strip()

        content = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        return self._chat_json(system_prompt, content)

    def generate_report_content(self, normalized_input: dict, experiment: dict, note: str | None = None) -> dict:
        experiment_name = normalized_input.get("experiment_name") or experiment.get("name") or "未知实验"
        experiment_description = normalized_input.get("experiment_description") or experiment.get("description") or ""
        note_text = str(note or "").strip()
        system_prompt = (
            "你是物理实验报告写作助手。只能根据给定 JSON 写实验报告内容，"
            "不得编造数据，不得修改字段名，只输出 JSON。"
            "你需要根据不同实验模板生成该实验专属的公式说明、数据处理说明、结果总结和误差分析。"
            "报告模板栏目固定为：原始实验数据、实验数据处理、实验结果、不确定度计算、误差分析、课后思考题。"
            "generic_processing_summary 应说明 OCR/录入数据如何整理成表格，不要重复输出完整原始数据表。"
            "generic_formula_lines 应重点用于“实验结果”栏目：针对每个需要计算的物理量，按脱式计算方式逐行列出公式、代入数据和计算结果。"
            "uncertainty_summary 应用于“不确定度计算”栏目，需按 A 类不确定度、B 类不确定度（如有）、总不确定度、最终 计算值 ± 不确定度 的顺序组织。"
            "本地程序不会替你做实验专属推导；请根据 experiment.fields 和 normalized_input 自行组织内容。"
            "若某个字段的 b_uncertainty.enabled 为 false，把它当作没有提供，不要写“未启用”“未提供”“为 0”等程序状态。"
            "如果所有字段都没有启用 B 类不确定度，不要提及 B 类不确定度或矢量合成。"
            "需要 Word 公式渲染的 LaTeX 片段必须使用 {{LaTeXbegin}} 和 {{LaTeXend}} 成对包裹，"
            "例如 {{LaTeXbegin}}T=2\\pi\\sqrt{L/g}{{LaTeXend}}。"
            "不要使用 $...$、$$...$$、\\(...\\)、\\[...\\] 或 Markdown 代码块包裹公式。"
            "generic_formula_lines 应返回简洁的公式说明；可包含普通中文说明和被标记包裹的 LaTeX 公式。"
            "LaTeX 公式尽量使用 \\frac{}{}、\\sqrt{}、上标 ^、下标 _ 和常见希腊字母命令。"
            "如果实验模板或数据不足以给出数值结果，请明确说明原因，但不要提及系统内部流程。"
            "如果提供了报告生成备注，只把它当作写作约束，不要原文复述到最终 JSON 里，也不要把它当成新的输出字段。"
        )
        user_payload = {
            "task": "根据实验模板和结构化数据生成实验报告内容。",
            "experiment": {
                "id": experiment.get("id") or normalized_input.get("experiment_id") or "",
                "name": experiment_name,
                "description": experiment_description,
                "category": experiment.get("category") or "",
                "report_mode": experiment.get("report_mode") or "llm",
                "fields": experiment.get("fields") or {},
            },
            "output_schema": {
                "generic_formula_lines": ["string，公式片段用 {{LaTeXbegin}}...{{LaTeXend}} 标记"],
                "generic_processing_summary": "string",
                "generic_result_headers": ["string"],
                "generic_result_rows": [["string"]],
                "uncertainty_summary": "string",
                "final_result": "string",
                "result_summary": "string",
                "error_analysis": "string",
                "thinking_answer": "string or null",
            },
            "normalized_input": normalized_input,
        }
        if note_text:
            user_payload["report_generation_note"] = note_text
        return self._chat_json(system_prompt, json.dumps(user_payload, ensure_ascii=False))

    def plan_plots(self, normalized_input: dict, experiment: dict, report_content: dict) -> dict:
        system_prompt = package_path("prompts", "plot_plan.txt").read_text(encoding="utf-8")
        options = normalized_input.get("options") or {}
        user_payload = {
            "task": "根据实验模板、结构化输入和报告内容判断是否需要绘图，并给出 safe_spec。",
            "plot_preferences": {
                "force_computer_plot": bool(options.get("force_computer_plot")),
                "forced_plot_count": int(options.get("forced_plot_count") or 1),
            },
            "experiment": {
                "id": experiment.get("id"),
                "name": experiment.get("name"),
                "description": experiment.get("description"),
                "fields": experiment.get("fields"),
            },
            "normalized_input": normalized_input,
            "report_content": report_content,
        }
        return self._chat_json(system_prompt, json.dumps(user_payload, ensure_ascii=False))

    def _chat_json(self, system_prompt: str, user_content) -> dict:
        payload = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
        }
        response = self._post_chat(payload)
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"模型响应格式异常：{response}") from exc
        return _loads_json_content(content)

    def _post_chat(self, payload: dict) -> dict:
        base_url = self.settings.base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"LLM API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"无法连接 LLM API：{exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError("LLM API 请求超时。") from exc


def _loads_json_content(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型没有返回合法 JSON：{content}") from exc


def _build_ocr_target_template(experiment_id: str, experiment: dict) -> dict:
    data = {}
    for field_name, field_meta in (experiment.get("fields") or {}).items():
        data[field_name] = {
            "label": field_meta.get("label") or field_name,
            "unit": field_meta.get("base_unit") or "",
            "values": [None, None],
            "b_uncertainty": {"enabled": False},
        }

    return {
        "experiment_id": experiment_id,
        "student": {
            "name": None,
            "student_id": None,
            "class_name": None,
            "date": None,
        },
        "options": {
            "include_thinking": False,
            "include_raw_appendix": True,
        },
        "data": data,
        "ocr_meta": {
            "confidence": 0.0,
            "recognized_cells": [],
            "warnings": [],
        },
    }

from __future__ import annotations

from pathlib import Path
import base64
import json
import mimetypes
import re
import zipfile
import zlib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

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

        data_url = _image_data_url(image_path)
        field_specs_json = json.dumps(field_specs, ensure_ascii=False, indent=2)
        target_json = json.dumps(target_template, ensure_ascii=False, indent=2)
        note_text = str(note or "").strip()

        system_prompt = (
            "你是物理实验数据录入助手。请从手写实验数据图片中识别实验数据，"
            "只输出 JSON，不要输出 Markdown。不要猜测缺失值；不确定的字段用 null，"
            "并在 warnings 中说明。数字必须保留原始识别字符串 raw 和 confidence。"
        )
        user_text = f"""
请识别图片中的实验数据，并整理成如下 JSON。当前选择的实验模板为：{experiment_label}，后台 experiment_id={experiment_id}。

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

    def generate_experiment_template(self, image_paths: list[Path], current_catalog: dict, note: str | None = None) -> dict:
        if not image_paths:
            raise LLMError("请至少选择一张用于生成模板的图片。")

        resolved_paths = []
        for image_path in image_paths:
            resolved_path = image_path.expanduser().resolve()
            if not resolved_path.is_file():
                raise LLMError(f"图片不存在或不是文件：{resolved_path}")
            resolved_paths.append(resolved_path)

        system_prompt = package_path("prompts", "template_ocr.txt").read_text(encoding="utf-8")
        note_text = str(note or "").strip()
        image_labels = [f"image_{index}: {path.name}" for index, path in enumerate(resolved_paths, start=1)]
        user_payload = {
            "task": "从多张实验讲义/报告照片中生成一个物理实验模板 JSON 对象。",
            "image_labels": image_labels,
            "user_note": note_text or "无",
            "existing_experiment_ids": [experiment.get("id") for experiment in (current_catalog.get("experiments") or []) if experiment.get("id")],
            "example_template": _example_template(current_catalog),
            "field_rules": [
                "fields 只允许列出实验表格中需要直接测量、记录或 OCR 录入的原始数据列。",
                "fields 禁止包含计算结果、拟合结果、最终结果、常量、公式推导中间量。",
                "整个 JSON 禁止包含任何不确定度字段、标签、描述或提示；B 类不确定度由本地 UI 复选框处理。",
            ],
            "output_schema": {
                "id": "string，必须不在 existing_experiment_ids 中，建议 exp_custom_<short_name>",
                "name": "string，实验名称",
                "category": "string，例如 mechanics/electricity/optics/custom",
                "description": "string，实验目的和核心公式摘要；不要写不确定度",
                "report_mode": "llm",
                "fields": {
                    "field_key": {
                        "label": "string，实验表格中原始测量列的中文名",
                        "base_unit": "string，基础单位；无量纲可用 ratio",
                        "accepted_units": ["string"],
                        "min": "number or null",
                        "max": "number or null",
                    }
                },
                "formula_hints": ["string，可包含 LaTeX，但不要用 Markdown"],
                "table_hints": ["string，描述表格列、重复测量行和应忽略的手写数据"],
            },
        }

        content = [{"type": "text", "text": json.dumps(user_payload, ensure_ascii=False)}]
        for path in resolved_paths:
            content.append({"type": "image_url", "image_url": {"url": _image_data_url(path)}})
        return self._chat_json(system_prompt, content)

    def generate_experiment_template_from_report(self, document_path: Path, current_catalog: dict, note: str | None = None) -> dict:
        resolved_path = document_path.expanduser().resolve()
        if not resolved_path.is_file():
            raise LLMError(f"实验报告文件不存在或不是文件：{resolved_path}")

        report_text, report_meta = _extract_report_document_text(resolved_path)
        if not report_text.strip():
            raise LLMError("无法从实验报告中提取可用于生成模板的文本，请确认文件不是纯图片扫描件或先做文字识别。")

        system_prompt = package_path("prompts", "template_report.txt").read_text(encoding="utf-8")
        note_text = str(note or "").strip()
        user_payload = {
            "task": "根据实验报告文本生成一个物理实验模板 JSON 对象。",
            "source_document": {
                "file_type": resolved_path.suffix.lower(),
                "text_excerpt": report_text,
                "character_count": report_meta["character_count"],
                "truncated": report_meta["truncated"],
            },
            "user_note": note_text or "无",
            "existing_experiment_ids": [experiment.get("id") for experiment in (current_catalog.get("experiments") or []) if experiment.get("id")],
            "example_template": _example_template(current_catalog),
            "field_rules": [
                "fields 只允许列出实验表格中需要直接测量、记录或 OCR 录入的原始数据列。",
                "fields 禁止包含计算结果、拟合结果、最终结果、常量、公式推导中间量。",
                "整个 JSON 禁止包含任何不确定度字段、标签、描述或提示；B 类不确定度由本地 UI 复选框处理。",
            ],
            "output_schema": {
                "id": "string，必须不在 existing_experiment_ids 中，建议 exp_custom_<short_name>",
                "name": "string，实验名称",
                "category": "string，例如 mechanics/electricity/optics/custom",
                "description": "string，实验目的和关键公式摘要，建议直接写入主要公式线索；不要写不确定度",
                "report_mode": "llm",
                "fields": {
                    "field_key": {
                        "label": "string，实验表格中原始测量列的中文名",
                        "base_unit": "string，基础单位；无量纲可用 ratio",
                        "accepted_units": ["string"],
                        "min": "number or null",
                        "max": "number or null",
                    }
                },
                "formula_hints": ["string，可包含 LaTeX，但不要用 Markdown"],
                "table_hints": ["string，描述表格列、重复测量行和应忽略的手写数据"],
            },
        }
        return self._chat_json(system_prompt, json.dumps(user_payload, ensure_ascii=False))

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
            "如果实验模板或数据不足以给出数值结果，请明确说明原因，但不要提及系统内部流程。切记，在回复中不要提及类似“识别置信度”，“OCR/录入”之类的词语。"
            "如果提供了报告生成备注，只把它当作写作约束，不要原文复述到最终 JSON 里，也不要把它当成新的输出字段。"
            "对于课后思考题部分，如果输入中给出了思考题的内容，则同时输出题目和答案。否则，自己设计若干个题目，也同时输出题目和答案。"
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
                "formula_hints": experiment.get("formula_hints") or [],
                "table_hints": experiment.get("table_hints") or [],
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
                "formula_hints": experiment.get("formula_hints") or [],
                "table_hints": experiment.get("table_hints") or [],
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


def _image_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{image_b64}"


def _extract_report_document_text(document_path: Path) -> tuple[str, dict]:
    suffix = document_path.suffix.lower()
    if suffix in {".docx", ".docm"}:
        text = _extract_docx_text(document_path)
    elif suffix == ".pdf":
        text = _extract_pdf_text(document_path)
    elif suffix == ".doc":
        text = _extract_legacy_doc_text(document_path)
    else:
        raise LLMError("仅支持 .pdf、.docx、.docm 和 .doc 实验报告文件。")

    normalized_text = _normalize_extracted_text(text)
    excerpt, truncated = _truncate_text(normalized_text)
    return excerpt, {
        "character_count": len(normalized_text),
        "truncated": truncated,
    }


def _extract_docx_text(document_path: Path) -> str:
    names = [
        "word/document.xml",
        *[f"word/header{index}.xml" for index in range(1, 10)],
        *[f"word/footer{index}.xml" for index in range(1, 10)],
    ]
    parts: list[str] = []
    with zipfile.ZipFile(document_path) as archive:
        for name in names:
            try:
                xml_text = archive.read(name)
            except KeyError:
                continue
            parts.append(_word_xml_to_text(xml_text))
    return "\n".join(part for part in parts if part.strip())


def _word_xml_to_text(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""

    lines: list[str] = []

    def walk(element: ET.Element) -> None:
        tag = element.tag
        local_tag = tag.rsplit("}", 1)[-1]
        if local_tag == "t":
            lines.append(element.text or "")
        elif local_tag == "tab":
            lines.append("\t")
        elif local_tag in {"br", "cr"}:
            lines.append("\n")
        for child in list(element):
            walk(child)
        if local_tag in {"p", "tr"}:
            lines.append("\n")

    walk(root)
    return "".join(lines)


def _extract_pdf_text(document_path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ModuleNotFoundError:
        return _extract_pdf_text_fallback(document_path.read_bytes())

    try:
        reader = PdfReader(str(document_path))
        texts = [page.extract_text() or "" for page in reader.pages]
        combined_text = "\n".join(texts).strip()
        if combined_text:
            return combined_text
    except Exception:
        pass
    return _extract_pdf_text_fallback(document_path.read_bytes())


def _extract_pdf_text_fallback(pdf_bytes: bytes) -> str:
    texts: list[str] = []
    stream_pattern = re.compile(br"stream\r?\n(.*?)\r?\nendstream", re.S)
    for match in stream_pattern.finditer(pdf_bytes):
        stream_bytes = match.group(1).strip(b"\r\n")
        prefix = pdf_bytes[max(0, match.start() - 200):match.start()]
        if b"/FlateDecode" in prefix:
            try:
                stream_bytes = zlib.decompress(stream_bytes)
            except Exception:
                pass
        texts.extend(_extract_pdf_strings(stream_bytes))
    if not texts:
        texts.extend(_extract_pdf_strings(pdf_bytes))
    return "\n".join(part for part in texts if part.strip())


def _extract_pdf_strings(content: bytes) -> list[str]:
    parts: list[str] = []
    for literal in re.findall(br"\((?:\\.|[^\\()])*\)", content, re.S):
        decoded = _decode_pdf_literal_string(literal)
        if decoded.strip():
            parts.append(decoded)
    for hex_value in re.findall(br"<([0-9A-Fa-f\s]+)>", content):
        decoded = _decode_pdf_hex_string(hex_value)
        if decoded.strip():
            parts.append(decoded)
    return parts


def _decode_pdf_literal_string(token: bytes) -> str:
    raw = token[1:-1]
    result = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte == 0x5C and index + 1 < len(raw):
            escaped = raw[index + 1]
            if escaped in b"nrtbf()\\":
                mapping = {
                    ord("n"): b"\n",
                    ord("r"): b"\r",
                    ord("t"): b"\t",
                    ord("b"): b"\b",
                    ord("f"): b"\f",
                    ord("("): b"(",
                    ord(")"): b")",
                    ord("\\"): b"\\",
                }
                result.extend(mapping[escaped])
                index += 2
                continue
            if 48 <= escaped <= 55:
                octal = bytes([escaped])
                lookahead = index + 2
                while lookahead < len(raw) and len(octal) < 3 and 48 <= raw[lookahead] <= 55:
                    octal += bytes([raw[lookahead]])
                    lookahead += 1
                result.append(int(octal.decode("ascii"), 8))
                index = lookahead
                continue
            if escaped in b"\r\n":
                index += 2
                while index < len(raw) and raw[index] in b"\r\n":
                    index += 1
                continue
            result.append(escaped)
            index += 2
            continue
        result.append(byte)
        index += 1
    return _decode_text_bytes(bytes(result))


def _decode_pdf_hex_string(token: bytes) -> str:
    hex_digits = re.sub(br"\s+", b"", token)
    if len(hex_digits) % 2:
        hex_digits += b"0"
    try:
        raw = bytes.fromhex(hex_digits.decode("ascii"))
    except ValueError:
        return ""
    return _decode_text_bytes(raw)


def _extract_legacy_doc_text(document_path: Path) -> str:
    try:
        raw_bytes = document_path.read_bytes()
    except OSError:
        return ""
    parts = []
    for match in re.finditer(br"(?:[\x09\x0a\x0d\x20-\x7e]\x00){4,}", raw_bytes):
        parts.append(match.group(0).decode("utf-16-le", errors="ignore"))
    for match in re.finditer(br"[\x09\x0a\x0d\x20-\x7e]{8,}", raw_bytes):
        parts.append(match.group(0).decode("latin1", errors="ignore"))
    if parts:
        return "\n".join(parts)
    return _decode_text_bytes(raw_bytes)


def _decode_text_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    candidates = []
    if raw.startswith(b"\xfe\xff"):
        candidates.extend(["utf-16-be", "utf-16-le"])
    elif raw.startswith(b"\xff\xfe"):
        candidates.extend(["utf-16-le", "utf-16-be"])
    elif _has_utf16_shape(raw):
        candidates.extend(["utf-16-be", "utf-16-le", "utf-8", "gb18030", "latin1"])
    else:
        candidates.extend(["utf-8", "gb18030", "latin1"])

    for encoding in candidates:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _looks_reasonable_text(text):
            return text
    return raw.decode("latin1", errors="ignore")


def _has_utf16_shape(raw: bytes) -> bool:
    if len(raw) < 8:
        return False
    even_zero_ratio = sum(1 for byte in raw[::2] if byte == 0) / max(len(raw[::2]), 1)
    odd_zero_ratio = sum(1 for byte in raw[1::2] if byte == 0) / max(len(raw[1::2]), 1)
    return even_zero_ratio >= 0.25 or odd_zero_ratio >= 0.25


def _looks_reasonable_text(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 8:
        return False
    printable = sum(1 for char in cleaned if char.isprintable() or char.isspace())
    return printable / max(len(cleaned), 1) >= 0.7


def _normalize_extracted_text(text: str) -> str:
    lines = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = re.sub(r"[ \t]+", " ", raw_line).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)


def _truncate_text(text: str, *, max_chars: int = 24000) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    head = max_chars * 7 // 10
    tail = max_chars - head
    return f"{text[:head]}\n[...内容已截断...]\n{text[-tail:]}", True


def _reference_render_contract(current_catalog: dict) -> list[str]:
    for experiment in current_catalog.get("experiments") or []:
        render_contract = experiment.get("render_contract")
        if isinstance(render_contract, list) and render_contract:
            return [str(item) for item in render_contract]
    return []


def _example_template(current_catalog: dict) -> dict:
    experiments = current_catalog.get("experiments") or []
    example = next((experiment for experiment in experiments if experiment.get("id") == "exp_001"), None)
    if example is None and experiments:
        example = experiments[0]
    if not isinstance(example, dict):
        return {}
    return {
        "id": example.get("id"),
        "name": example.get("name"),
        "category": example.get("category"),
        "description": example.get("description"),
        "report_mode": example.get("report_mode") or "llm",
        "fields": example.get("fields") or {},
    }


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

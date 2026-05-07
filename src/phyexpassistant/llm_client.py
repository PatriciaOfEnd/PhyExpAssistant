from __future__ import annotations

from pathlib import Path
import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request

from .settings import Settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings):
        if not settings.is_llm_ready:
            raise LLMError("请先在交互界面设置 API Key、Base URL 和 Model。")
        self.settings = settings

    def extract_handwritten_data(self, image_path: Path, experiment_id: str) -> dict:
        image_path = image_path.expanduser().resolve()
        if not image_path.exists():
            raise LLMError(f"图片不存在：{image_path}")

        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        data_url = f"data:{mime_type};base64,{image_b64}"

        system_prompt = (
            "你是物理实验数据录入助手。请从手写实验数据图片中识别实验数据，"
            "只输出 JSON，不要输出 Markdown。不要猜测缺失值；不确定的字段用 null，"
            "并在 warnings 中说明。数字必须保留原始识别字符串 raw 和 confidence。"
        )
        user_text = f"""
请识别图片中的实验数据，并整理成如下 JSON。当前 demo 只支持 experiment_id={experiment_id} 的单摆实验。

目标 JSON：
{{
  "experiment_id": "exp_001",
  "student": {{
    "name": null,
    "student_id": null,
    "class_name": null,
    "date": null
  }},
  "options": {{
    "include_thinking": false,
    "include_raw_appendix": true
  }},
  "data": {{
    "length": {{"unit": "m", "values": [0.5, 0.6], "b_uncertainty": {{"enabled": false}}}},
    "period": {{"unit": "s", "values": [1.42, 1.55], "b_uncertainty": {{"enabled": false}}}}
  }},
  "ocr_meta": {{
    "confidence": 0.0,
    "recognized_cells": [
      {{"field": "length", "raw": "50.0", "value": 50.0, "unit": "cm", "confidence": 0.8}}
    ],
    "warnings": []
  }}
}}

要求：
1. length 表示摆长，period 表示周期。
2. 如果图片里单位是 cm/mm/ms，请保留对应 unit，不要擅自换算。
3. values 中只放数字或 null，不要放带单位的字符串。
4. 行数必须对应；无法确认的值用 null。
""".strip()

        content = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        return self._chat_json(system_prompt, content)

    def generate_narrative(self, normalized_input: dict, compute_result: dict) -> dict:
        system_prompt = (
            "你是物理实验报告写作助手。只能根据给定 JSON 写报告文字，"
            "不得修改、重算或编造任何数值。只输出 JSON。"
            "若某个 B 类不确定度来源的 enabled 为 false，应视为该项不适用于本实验，"
            "不要写“未启用”“未提供”“为 0”等程序状态描述；"
            "若所有 B 类不确定度均不适用，不要提及 B 类不确定度或矢量合成。"
            "文字应采用正式实验报告语气，不要出现“系统提示”“输入中”“设置中”等程序口吻。"
        )
        user_payload = {
            "task": "根据锁定的计算结果生成实验报告中的结果总结和误差分析。",
            "output_schema": {
                "result_summary": "string",
                "error_analysis": "string",
                "thinking_answer": "string or null",
            },
            "normalized_input": normalized_input,
            "compute_result": compute_result,
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

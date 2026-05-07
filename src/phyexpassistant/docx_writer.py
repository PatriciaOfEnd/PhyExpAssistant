from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
import struct
import zipfile


EMU_PER_INCH = 914400
EMU_PER_PIXEL = 9525
MAX_IMAGE_WIDTH_EMU = int(5.8 * EMU_PER_INCH)
LATEX_BEGIN = "{{LaTeXbegin}}"
LATEX_END = "{{LaTeXend}}"

LATEX_SYMBOLS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "theta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "φ",
    "varphi": "φ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Phi": "Φ",
    "Omega": "Ω",
    "times": "×",
    "cdot": "·",
    "pm": "±",
    "mp": "∓",
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "neq": "≠",
    "approx": "≈",
    "sim": "∼",
    "propto": "∝",
    "infty": "∞",
    "degree": "°",
    "circ": "°",
    "sum": "∑",
}

LATEX_FUNCTIONS = {"sin", "cos", "tan", "cot", "ln", "log", "exp", "max", "min", "lim"}


def write_docx(path: Path, context: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original_photo = _collect_original_photo(context, base_dir=path.parent)
    figures = _collect_figures(context, base_dir=path.parent)
    images = [image for image in [original_photo, *figures] if image]
    _assign_image_metadata(images)
    document_xml = _document_xml(context, figures, original_photo)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", _content_types_xml(images))
        docx.writestr("_rels/.rels", _package_relationships_xml())
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/_rels/document.xml.rels", _document_relationships_xml(images))
        docx.writestr("word/styles.xml", _styles_xml())
        docx.writestr("word/settings.xml", _settings_xml())
        for image in images:
            docx.writestr(f"word/media/{image['media_name']}", Path(image["path"]).read_bytes())


def _document_xml(context: dict, figures: list[dict], original_photo: dict | None) -> str:
    body_parts: list[str] = []
    body_parts.append(_paragraph(context["experiment_name"], style="Title", align="center"))
    body_parts.append(_paragraph(_student_line(context), style="StudentLine", align="center"))
    body_parts.extend(_generic_report_body_parts(context, figures, original_photo))
    body_parts.append(_section_properties())
    body = "".join(body_parts)
    return _document_package_xml(body)


def _document_package_xml(body: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
  xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>{body}</w:body>
</w:document>'''


def _generic_report_body_parts(context: dict, figures: list[dict], original_photo: dict | None) -> list[str]:
    body_parts: list[str] = []

    if _section_enabled(context, "raw_data"):
        body_parts.append(_section_heading("一、原始实验数据"))
        if original_photo:
            body_parts.append(_image_paragraph(original_photo))
            body_parts.append(_paragraph("实验报告照片", style="Caption", align="center"))
        else:
            body_parts.append(_paragraph("未提供实验报告照片。"))

    if _section_enabled(context, "data_processing"):
        body_parts.append(_section_heading("二、实验数据处理"))
        body_parts.append(_table(context["raw_headers"], context["raw_rows"]))
        if context.get("generic_processing_summary"):
            body_parts.append(_paragraph(context["generic_processing_summary"]))
        if figures and _section_enabled(context, "computer_plot"):
            body_parts.append(_sub_heading("计算机绘图"))
            for figure in figures:
                body_parts.append(_image_paragraph(figure))
                body_parts.append(_paragraph(f"图 {figure['index']}  {figure.get('caption', '计算机绘图')}", style="Caption", align="center"))
                if figure.get("description"):
                    body_parts.append(_paragraph(figure["description"]))

    if _section_enabled(context, "result_summary"):
        body_parts.append(_section_heading("三、实验结果"))
        body_parts.append(_sub_heading("1. 公式与脱式计算"))
        for formula in context.get("generic_formula_lines") or []:
            body_parts.append(_paragraph(formula, style="Formula", align="center"))
        result_rows = context.get("generic_result_rows") or []
        if result_rows:
            body_parts.append(_sub_heading("2. 计算结果汇总"))
            body_parts.append(_table(context.get("generic_result_headers") or ["项目", "内容"], result_rows))

    if _section_enabled(context, "uncertainty") and context.get("uncertainty_summary"):
        body_parts.append(_section_heading("四、不确定度计算"))
        body_parts.append(_paragraph(context["uncertainty_summary"]))
        if context.get("final_result"):
            body_parts.append(_paragraph(f"最终结果：{context['final_result']}", bold=True))

    if context.get("result_summary") or context.get("error_analysis"):
        body_parts.append(_section_heading("五、误差分析与结果讨论"))
        if context.get("result_summary"):
            body_parts.append(_paragraph(context["result_summary"]))
        if context.get("error_analysis"):
            body_parts.append(_paragraph(context["error_analysis"]))

    if context.get("thinking_answer") and _section_enabled(context, "thinking"):
        body_parts.append(_section_heading("六、课后思考题"))
        body_parts.append(_paragraph(context["thinking_answer"]))

    return body_parts


def _student_line(context: dict) -> str:
    parts = [context.get("student_name") or "未填写", context.get("student_id") or "未填写"]
    if context.get("class_name"):
        parts.append(context["class_name"])
    if context.get("experiment_date"):
        parts.append(context["experiment_date"])
    return "  ".join(parts)


def _section_enabled(context: dict, key: str) -> bool:
    section_options = context.get("section_options") or {}
    return bool(section_options.get(key, True))


def _collect_original_photo(context: dict, *, base_dir: Path | None = None) -> dict | None:
    raw_photo_path = context.get("original_photo_path")
    if not raw_photo_path:
        return None
    photo_path = _resolve_figure_path(raw_photo_path, base_dir=base_dir)
    if not photo_path.exists():
        return None
    width_px, height_px = _image_size(photo_path)
    width_emu, height_emu = _scaled_image_size(width_px, height_px)
    return {
        "path": str(photo_path),
        "caption": "实验报告照片",
        "description": "原始实验数据照片。",
        "position": "original_data",
        "width_emu": width_emu,
        "height_emu": height_emu,
    }


def _collect_figures(context: dict, *, base_dir: Path | None = None) -> list[dict]:
    figures = []
    for index, figure in enumerate(context.get("figures") or [], start=1):
        raw_figure_path = figure.get("path", "")
        if not raw_figure_path:
            continue
        figure_path = _resolve_figure_path(raw_figure_path, base_dir=base_dir)
        if not figure_path.exists():
            continue
        width_px, height_px = _image_size(figure_path)
        width_emu, height_emu = _scaled_image_size(width_px, height_px)
        figures.append({
            **figure,
            "path": str(figure_path),
            "index": index,
            "width_emu": width_emu,
            "height_emu": height_emu,
        })
    return figures


def _assign_image_metadata(images: list[dict]) -> None:
    for media_index, image in enumerate(images, start=1):
        extension = _image_extension(Path(image["path"]))
        image["media_name"] = f"image{media_index}.{extension}"
        image["r_id"] = f"rIdImage{media_index}"
        image["doc_pr_id"] = media_index


def _scaled_image_size(width_px: int, height_px: int) -> tuple[int, int]:
    width_emu = width_px * EMU_PER_PIXEL
    height_emu = height_px * EMU_PER_PIXEL
    if width_emu > MAX_IMAGE_WIDTH_EMU:
        scale = MAX_IMAGE_WIDTH_EMU / width_emu
        width_emu = int(width_emu * scale)
        height_emu = int(height_emu * scale)
    return width_emu, height_emu


def _resolve_figure_path(raw_path: object, *, base_dir: Path | None = None) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        return Path(".__missing_figure__")

    candidates: list[Path] = []

    def add_candidate(candidate: Path | str) -> None:
        path = Path(candidate)
        if path not in candidates:
            candidates.append(path)

    add_candidate(text)

    normalized = text.replace("\\", "/")
    add_candidate(normalized)

    if base_dir is not None:
        add_candidate(base_dir / text)
        add_candidate(base_dir / normalized)

    if len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/":
        drive = normalized[0].lower()
        rest = normalized[3:]
        add_candidate(Path(f"/mnt/{drive}") / rest)
        add_candidate(Path(f"/media/{drive}") / rest)

    cwd = Path.cwd()
    add_candidate(cwd / normalized)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]


def _image_extension(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "jpg":
        return "jpeg"
    if suffix in {"png", "jpeg", "bmp", "gif", "tif", "tiff", "webp"}:
        return suffix
    return "png"


def _image_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        size = _jpeg_size(data)
        if size:
            return size
    if data[:2] == b"BM" and len(data) >= 26:
        width = int.from_bytes(data[18:22], "little", signed=True)
        height = int.from_bytes(data[22:26], "little", signed=True)
        if width and height:
            return abs(width), abs(height)
    return 960, 540


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += segment_length
    return None


def _section_heading(text: str) -> str:
    return _paragraph(text, style="Heading1")


def _sub_heading(text: str) -> str:
    return _paragraph(text, style="Heading2")


def _paragraph(text: object, *, style: str | None = "Normal", bold: bool = False, align: str | None = None) -> str:
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    align_xml = f'<w:jc w:val="{align}"/>' if align else ""
    bold_xml = "<w:b/>" if bold else ""
    runs_xml = _paragraph_content_runs(text, bold=bold)
    return f"<w:p><w:pPr>{style_xml}{align_xml}</w:pPr>{runs_xml}</w:p>"


def _info_table(context: dict) -> str:
    return _table(
        [],
        [
            ["实验名称", context["experiment_name"], "实验日期", context["experiment_date"]],
            ["姓名", context["student_name"], "学号", context["student_id"]],
            ["班级", context["class_name"], "实验编号", context["experiment_id"]],
        ],
        has_header=False,
    )


def _table(headers: list[str], rows: list[list[object]], *, has_header: bool = True) -> str:
    table_rows = []
    if has_header and headers:
        table_rows.append(_table_row(headers, header=True))
    table_rows.extend(_table_row(row) for row in rows)
    borders = (
        '<w:tblBorders><w:top w:val="single" w:sz="8" w:space="0" w:color="333333"/>'
        '<w:left w:val="single" w:sz="8" w:space="0" w:color="333333"/>'
        '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="333333"/>'
        '<w:right w:val="single" w:sz="8" w:space="0" w:color="333333"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="777777"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="777777"/></w:tblBorders>'
    )
    table_pr = f'<w:tblPr><w:tblW w:w="0" w:type="auto"/><w:jc w:val="center"/>{borders}</w:tblPr>'
    return f'<w:tbl>{table_pr}{"".join(table_rows)}</w:tbl>'


def _table_row(row: list[object], *, header: bool = False) -> str:
    return f"<w:tr>{''.join(_table_cell(value, header=header) for value in row)}</w:tr>"


def _table_cell(value: object, *, header: bool = False) -> str:
    shade = '<w:shd w:fill="EDEDED"/>' if header else ""
    return (
        f'<w:tc><w:tcPr><w:tcW w:w="2400" w:type="dxa"/>{shade}</w:tcPr>'
        f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr>{_paragraph_content_runs(value, bold=header)}</w:p></w:tc>'
    )


def _paragraph_content_runs(text: object, *, bold: bool = False) -> str:
    segments = _split_marked_latex(str(text))
    if segments is None:
        return _text_run(text, bold=bold)

    runs: list[str] = []
    for segment_type, segment_value in segments:
        if segment_type == "text":
            if segment_value:
                runs.append(_text_run(segment_value, bold=bold))
        elif segment_type == "latex":
            math_xml = _latex_to_omml(segment_value)
            if math_xml:
                runs.append(f"<m:oMath>{math_xml}</m:oMath>")
    if runs:
        return "".join(runs)
    return _text_run("", bold=bold)


def _text_run(text: object, *, bold: bool = False) -> str:
    safe = escape(str(text))
    bold_xml = "<w:b/>" if bold else ""
    return f'<w:r><w:rPr>{bold_xml}</w:rPr><w:t xml:space="preserve">{safe}</w:t></w:r>'


def _split_marked_latex(text: str) -> list[tuple[str, str]] | None:
    if LATEX_BEGIN not in text and LATEX_END not in text:
        return [("text", text)]

    segments: list[tuple[str, str]] = []
    cursor = 0
    while True:
        begin_index = text.find(LATEX_BEGIN, cursor)
        if begin_index < 0:
            if cursor < len(text):
                segments.append(("text", text[cursor:]))
            break
        end_index = text.find(LATEX_END, begin_index + len(LATEX_BEGIN))
        if end_index < 0:
            return None
        if begin_index > cursor:
            segments.append(("text", text[cursor:begin_index]))
        latex_content = text[begin_index + len(LATEX_BEGIN) : end_index].strip()
        segments.append(("latex", latex_content))
        cursor = end_index + len(LATEX_END)
    return segments


def _latex_to_omml(latex: str) -> str:
    latex = _normalize_latex(latex)
    parser = _LatexParser(latex)
    return parser.parse()


def _normalize_latex(latex: str) -> str:
    text = latex.strip()
    if text.startswith("$$") and text.endswith("$$") and len(text) >= 4:
        text = text[2:-2].strip()
    elif text.startswith("$") and text.endswith("$") and len(text) >= 2:
        text = text[1:-1].strip()
    elif text.startswith("\\[") and text.endswith("\\]") and len(text) >= 4:
        text = text[2:-2].strip()
    elif text.startswith("\\(") and text.endswith("\\)") and len(text) >= 4:
        text = text[2:-2].strip()
    text = text.replace("\\\\", "\\")
    return text


class _LatexParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0

    def parse(self) -> str:
        return self._parse_expression()

    def _parse_expression(self, stop_char: str | None = None) -> str:
        elements: list[str] = []
        while self.index < len(self.text):
            if stop_char is not None and self.text[self.index] == stop_char:
                self.index += 1
                break
            if self.text[self.index].isspace():
                self.index += 1
                continue
            element = self._parse_atom()
            if not element:
                continue
            while self.index < len(self.text) and self.text[self.index] in "^_":
                marker = self.text[self.index]
                self.index += 1
                script = self._parse_script_argument()
                if marker == "^":
                    element = _apply_superscript(element, script)
                else:
                    element = _apply_subscript(element, script)
            elements.append(element)
        return "".join(elements)

    def _parse_script_argument(self) -> str:
        self._skip_spaces()
        if self.index >= len(self.text):
            return _math_run("")
        if self.text[self.index] == "{":
            self.index += 1
            return self._parse_expression(stop_char="}")
        return self._parse_atom()

    def _parse_atom(self) -> str:
        self._skip_spaces()
        if self.index >= len(self.text):
            return ""
        char = self.text[self.index]
        if char == "{":
            self.index += 1
            return self._parse_expression(stop_char="}")
        if char == "}":
            self.index += 1
            return _math_run("}")
        if char in "^_":
            self.index += 1
            return _math_run(char)
        if char == "\\":
            return self._parse_command()
        if char in ")],.;:+-=*/<>|":
            self.index += 1
            return _math_run(char)
        start = self.index
        while self.index < len(self.text):
            current = self.text[self.index]
            if current in "{}_\\^" or current.isspace() or current in ")],.;:+-=*/<>|":
                break
            self.index += 1
        return _math_run(self.text[start:self.index])

    def _parse_command(self) -> str:
        self.index += 1
        if self.index >= len(self.text):
            return _math_run("\\")

        command_char = self.text[self.index]
        if not command_char.isalpha():
            self.index += 1
            return _command_symbol(command_char)

        start = self.index
        while self.index < len(self.text) and self.text[self.index].isalpha():
            self.index += 1
        command = self.text[start:self.index]

        if command == "frac":
            numerator = self._parse_required_group()
            denominator = self._parse_required_group()
            return _math_fraction(numerator, denominator)
        if command == "sqrt":
            self._skip_optional_bracket()
            radicand = self._parse_required_group()
            return _math_radical(radicand)
        if command in {"bar", "overline"}:
            return _math_bar(self._parse_required_group())
        if command == "text":
            return _math_run(self._read_required_group_text())
        if command == "mathrm":
            return _math_run(self._read_required_group_text())
        if command == "left" or command == "right":
            self._skip_spaces()
            if self.index < len(self.text):
                if self.text[self.index] == "\\":
                    return self._parse_command()
                self.index += 1
                return _math_run(self.text[self.index - 1])
            return ""
        if command in {",", ";", "!", "quad", "qquad"}:
            return _math_run(" ")

        mapped = LATEX_SYMBOLS.get(command)
        if mapped is not None:
            return _math_run(mapped)
        if command in LATEX_FUNCTIONS:
            return _math_run(command)
        return _math_run(command)

    def _parse_required_group(self) -> str:
        self._skip_spaces()
        if self.index >= len(self.text):
            return _math_run("")
        if self.text[self.index] == "{":
            self.index += 1
            return self._parse_expression(stop_char="}")
        return self._parse_atom()

    def _read_required_group_text(self) -> str:
        self._skip_spaces()
        if self.index >= len(self.text) or self.text[self.index] != "{":
            return ""
        self.index += 1
        depth = 1
        start = self.index
        while self.index < len(self.text) and depth > 0:
            current = self.text[self.index]
            if current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    result = self.text[start:self.index]
                    self.index += 1
                    return _strip_known_commands(result)
            self.index += 1
        return _strip_known_commands(self.text[start:])

    def _skip_optional_bracket(self) -> None:
        self._skip_spaces()
        if self.index < len(self.text) and self.text[self.index] == "[":
            self.index += 1
            depth = 1
            while self.index < len(self.text) and depth > 0:
                current = self.text[self.index]
                if current == "[":
                    depth += 1
                elif current == "]":
                    depth -= 1
                self.index += 1

    def _skip_spaces(self) -> None:
        while self.index < len(self.text) and self.text[self.index].isspace():
            self.index += 1


def _strip_known_commands(text: str) -> str:
    return text.replace("\\,", " ").replace("\\;", " ").replace("\\!", "").replace("\\quad", " ").replace("\\qquad", " ")


def _math_run(text: object) -> str:
    safe = escape(str(text))
    return f'<m:r><m:t xml:space="preserve">{safe}</m:t></m:r>'


def _command_symbol(command_char: str) -> str:
    if command_char in {",", ";"}:
        return _math_run(" ")
    if command_char == "!":
        return ""
    return _math_run(LATEX_SYMBOLS.get(command_char, command_char))


def _apply_superscript(base: str, sup: str) -> str:
    return f"<m:sSup><m:e>{base}</m:e><m:sup>{sup}</m:sup></m:sSup>"


def _apply_subscript(base: str, sub: str) -> str:
    return f"<m:sSub><m:e>{base}</m:e><m:sub>{sub}</m:sub></m:sSub>"


def _apply_sub_superscript(base: str, sub: str, sup: str) -> str:
    return f"<m:sSubSup><m:e>{base}</m:e><m:sub>{sub}</m:sub><m:sup>{sup}</m:sup></m:sSubSup>"


def _math_fraction(numerator: str, denominator: str) -> str:
    return f'<m:f><m:fPr><m:type m:val="bar"/></m:fPr><m:num>{numerator}</m:num><m:den>{denominator}</m:den></m:f>'


def _math_radical(radicand: str) -> str:
    return f'<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/><m:e>{radicand}</m:e></m:rad>'


def _math_bar(element: str) -> str:
    return f'<m:bar><m:barPr><m:pos m:val="top"/></m:barPr><m:e>{element}</m:e></m:bar>'


def _image_paragraph(figure: dict) -> str:
    rid = figure["r_id"]
    width_emu = figure["width_emu"]
    height_emu = figure["height_emu"]
    name = escape(figure.get("caption") or "figure")
    doc_pr_id = figure.get("doc_pr_id") or figure.get("index") or 1
    return f'''
<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>
  <wp:inline distT="0" distB="0" distL="0" distR="0">
    <wp:extent cx="{width_emu}" cy="{height_emu}"/>
    <wp:docPr id="{doc_pr_id}" name="{name}"/>
    <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
      <pic:pic>
        <pic:nvPicPr><pic:cNvPr id="{doc_pr_id}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>
        <pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
        <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width_emu}" cy="{height_emu}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
      </pic:pic>
    </a:graphicData></a:graphic>
  </wp:inline>
</w:drawing></w:r></w:p>'''


def _section_properties() -> str:
    return '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/><w:cols w:space="425"/></w:sectPr>'


def _content_types_xml(images: list[dict]) -> str:
    image_content_types = {
        "png": "image/png",
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "bmp": "image/bmp",
        "gif": "image/gif",
        "tif": "image/tiff",
        "tiff": "image/tiff",
        "webp": "image/webp",
    }
    image_defaults = []
    for image in images:
        extension = Path(image["media_name"]).suffix.lower().lstrip(".")
        content_type = image_content_types.get(extension)
        if content_type:
            image_defaults.append(f'<Default Extension="{extension}" ContentType="{content_type}"/>')
    image_defaults_xml = "\n  ".join(dict.fromkeys(image_defaults))
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  {image_defaults_xml}
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>'''


def _package_relationships_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''


def _document_relationships_xml(images: list[dict]) -> str:
    relationships = [
        '<Relationship Id="rStyle" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
        '<Relationship Id="rSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>',
    ]
    for image in images:
        relationships.append(f'<Relationship Id="{image["r_id"]}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{image["media_name"]}"/>')
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {''.join(relationships)}
</Relationships>'''


def _styles_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体" w:hAnsi="Times New Roman"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:line="360" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr><w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体" w:hAnsi="Times New Roman"/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:spacing w:before="120" w:after="160"/><w:jc w:val="center"/></w:pPr><w:rPr><w:rFonts w:eastAsia="黑体" w:ascii="Times New Roman"/><w:b/><w:sz w:val="36"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="StudentLine"><w:name w:val="StudentLine"/><w:pPr><w:spacing w:after="240"/><w:jc w:val="center"/></w:pPr><w:rPr><w:rFonts w:eastAsia="宋体"/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="Heading 1"/><w:pPr><w:spacing w:before="240" w:after="120"/><w:keepNext/></w:pPr><w:rPr><w:rFonts w:eastAsia="黑体"/><w:b/><w:sz w:val="28"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="Heading 2"/><w:pPr><w:spacing w:before="120" w:after="80"/><w:keepNext/></w:pPr><w:rPr><w:rFonts w:eastAsia="宋体"/><w:b/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Formula"><w:name w:val="Formula"/><w:pPr><w:spacing w:before="60" w:after="60"/><w:jc w:val="center"/></w:pPr><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math" w:eastAsia="Cambria Math"/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="Caption"/><w:pPr><w:spacing w:before="80" w:after="160"/><w:jc w:val="center"/></w:pPr><w:rPr><w:rFonts w:eastAsia="宋体"/><w:sz w:val="20"/><w:i/></w:rPr></w:style>
</w:styles>'''


def _settings_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
  <w:defaultTabStop w:val="420"/>
  <m:mathPr><m:mathFont m:val="Cambria Math"/><m:brkBin m:val="before"/><m:brkBinSub m:val="--"/><m:smallFrac m:val="0"/><m:dispDef/><m:lMargin m:val="0"/><m:rMargin m:val="0"/></m:mathPr>
</w:settings>'''

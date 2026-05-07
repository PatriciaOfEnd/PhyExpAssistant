from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
import struct
import zipfile


EMU_PER_INCH = 914400
EMU_PER_PIXEL = 9525
MAX_IMAGE_WIDTH_EMU = int(5.8 * EMU_PER_INCH)


def write_docx(path: Path, context: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figures = _collect_figures(context, base_dir=path.parent)
    document_xml = _document_xml(context, figures)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", _content_types_xml(figures))
        docx.writestr("_rels/.rels", _package_relationships_xml())
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/_rels/document.xml.rels", _document_relationships_xml(figures))
        docx.writestr("word/styles.xml", _styles_xml())
        docx.writestr("word/settings.xml", _settings_xml())
        for index, figure in enumerate(figures, start=1):
            docx.writestr(f"word/media/image{index}.png", Path(figure["path"]).read_bytes())


def _document_xml(context: dict, figures: list[dict]) -> str:
    body_parts: list[str] = []
    body_parts.append(_paragraph(context["experiment_name"], style="Title", align="center"))
    body_parts.append(_paragraph(_student_line(context), style="StudentLine", align="center"))
    body_parts.extend(_generic_report_body_parts(context, figures))
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


def _generic_report_body_parts(context: dict, figures: list[dict]) -> list[str]:
    body_parts: list[str] = []

    if _section_enabled(context, "basic_info"):
        body_parts.append(_section_heading("一、实验基本信息"))
        body_parts.append(_info_table(context))
        if context.get("experiment_description"):
            body_parts.append(_paragraph(f"实验说明：{context['experiment_description']}"))

    if _section_enabled(context, "raw_data"):
        body_parts.append(_section_heading("二、实验数据记录"))
        body_parts.append(_table(context["raw_headers"], context["raw_rows"]))

    if _section_enabled(context, "data_processing"):
        body_parts.append(_section_heading("三、实验数据处理"))
        body_parts.append(_sub_heading("1. 实验原理与处理方法"))
        for formula in context.get("generic_formula_lines") or []:
            body_parts.append(_paragraph(formula, style="Formula", align="center"))
        if context.get("generic_processing_summary"):
            body_parts.append(_paragraph(context["generic_processing_summary"]))
        result_rows = context.get("generic_result_rows") or []
        if result_rows:
            body_parts.append(_sub_heading("2. 数据处理结果"))
            body_parts.append(_table(context.get("generic_result_headers") or ["项目", "内容"], result_rows))
        if figures and _section_enabled(context, "computer_plot"):
            body_parts.append(_sub_heading("3. 计算机绘图"))
            for figure in figures:
                body_parts.append(_image_paragraph(figure))
                body_parts.append(_paragraph(f"图 {figure['index']}  {figure.get('caption', '计算机绘图')}", style="Caption", align="center"))
                if figure.get("description"):
                    body_parts.append(_paragraph(figure["description"]))

    if _section_enabled(context, "uncertainty") and context.get("uncertainty_summary"):
        body_parts.append(_section_heading("四、不确定度分析"))
        body_parts.append(_paragraph(context["uncertainty_summary"]))
        if context.get("final_result"):
            body_parts.append(_paragraph(f"最终结果：{context['final_result']}", bold=True))

    if _section_enabled(context, "result_summary"):
        body_parts.append(_section_heading("五、实验结果分析"))
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


def _collect_figures(context: dict, *, base_dir: Path | None = None) -> list[dict]:
    figures = []
    for index, figure in enumerate(context.get("figures") or [], start=1):
        raw_figure_path = figure.get("path", "")
        if not raw_figure_path:
            continue
        figure_path = _resolve_figure_path(raw_figure_path, base_dir=base_dir)
        if not figure_path.exists():
            continue
        width_px, height_px = _png_size(figure_path)
        width_emu = width_px * EMU_PER_PIXEL
        height_emu = height_px * EMU_PER_PIXEL
        if width_emu > MAX_IMAGE_WIDTH_EMU:
            scale = MAX_IMAGE_WIDTH_EMU / width_emu
            width_emu = int(width_emu * scale)
            height_emu = int(height_emu * scale)
        figures.append({
            **figure,
            "path": str(figure_path),
            "index": index,
            "r_id": f"rId{index}",
            "width_emu": width_emu,
            "height_emu": height_emu,
        })
    return figures


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


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return 960, 540
    return struct.unpack(">II", data[16:24])


def _section_heading(text: str) -> str:
    return _paragraph(text, style="Heading1")


def _sub_heading(text: str) -> str:
    return _paragraph(text, style="Heading2")


def _paragraph(text: object, *, style: str | None = "Normal", bold: bool = False, align: str | None = None) -> str:
    safe = escape(str(text))
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    align_xml = f'<w:jc w:val="{align}"/>' if align else ""
    bold_xml = "<w:b/>" if bold else ""
    return (
        f"<w:p><w:pPr>{style_xml}{align_xml}</w:pPr>"
        f"<w:r><w:rPr>{bold_xml}</w:rPr><w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"
    )


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
    safe = escape(str(value))
    shade = '<w:shd w:fill="EDEDED"/>' if header else ""
    bold = "<w:b/>" if header else ""
    return (
        f'<w:tc><w:tcPr><w:tcW w:w="2400" w:type="dxa"/>{shade}</w:tcPr>'
        f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr>{bold}</w:rPr>'
        f'<w:t xml:space="preserve">{safe}</w:t></w:r></w:p></w:tc>'
    )


def _image_paragraph(figure: dict) -> str:
    rid = figure["r_id"]
    width_emu = figure["width_emu"]
    height_emu = figure["height_emu"]
    name = escape(figure.get("caption") or "figure")
    return f'''
<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>
  <wp:inline distT="0" distB="0" distL="0" distR="0">
    <wp:extent cx="{width_emu}" cy="{height_emu}"/>
    <wp:docPr id="{figure['index']}" name="{name}"/>
    <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
      <pic:pic>
        <pic:nvPicPr><pic:cNvPr id="{figure['index']}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>
        <pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
        <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width_emu}" cy="{height_emu}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
      </pic:pic>
    </a:graphicData></a:graphic>
  </wp:inline>
</w:drawing></w:r></w:p>'''


def _section_properties() -> str:
    return '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/><w:cols w:space="425"/></w:sectPr>'


def _content_types_xml(figures: list[dict]) -> str:
    png_default = '<Default Extension="png" ContentType="image/png"/>' if figures else ""
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  {png_default}
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>'''


def _package_relationships_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''


def _document_relationships_xml(figures: list[dict]) -> str:
    relationships = [
        '<Relationship Id="rStyle" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
        '<Relationship Id="rSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>',
    ]
    for index, figure in enumerate(figures, start=1):
        relationships.append(f'<Relationship Id="{figure["r_id"]}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image{index}.png"/>')
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

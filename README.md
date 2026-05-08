# PhyExpAssistant

> [!WARNING]
> 该项目全部由 LLM 生成 (vibe coding) ，可能存在包括但不限于架构混乱，逻辑不明，大量 bug 等，在人工介入修改前，不建议任何人审计此项目。为您带来的糟糕阅读体验，我们深感抱歉。开始审计此项目，代表着您已经充分认识到审计此项目可能带来的潜在风险，开发者对您可能出现的任何心脑血管疾病不负任何责任。


PhyExpAssistant 是一款基于 LLM 的，支持交互式设置 LLM API Key 和 Model，手动录入或手写识别实验数据，完成校验、计算、LLM 报告文字生成，并输出 `.docx` 报告和运行产物的软件，支持 CLI 交互和 UI 交互。

## 获取源码

如果你要先把仓库克隆到本地，可以直接使用 `git clone`：

```bash
git clone https://github.com/PatriciaOfEnd/PhyExpAssistant.git
cd PhyExpAssistant
```

如果你已经配置了 SSH，也可以改用：

```bash
git clone git@github.com:PatriciaOfEnd/PhyExpAssistant.git
cd PhyExpAssistant
```

## 当前能力

- 支持实验模板：`exp_001` 单摆测重力加速度、`exp_002` 单摆周期与摆长关系验证、`exp_003` 惠斯通电桥测电阻。
- 支持输入：手动录入、手写图片 LLM OCR 草稿。
- 支持模板管理：UI 右侧“模板管理”页可编辑、校验和保存模板，也可粘贴、导入 JSON 或通过 Agent OCR 从图片生成新模板。
- 支持 LLM 报告生成：根据实验模板生成公式说明、数据处理、结果总结和误差分析。
- 支持 UI 备注分流：手写识别备注只影响 OCR prompt，报告生成备注默认关闭且只影响报告文字 prompt。
- 支持公式标记渲染：LLM 返回的 LaTeX 公式需使用 `{{LaTeXbegin}}...{{LaTeXend}}` 标记，本地生成 Word 时会转为 Word 公式。
- 支持不确定度输入：每个数据字段可配置 B 类不确定度，并由报告生成流程按模板处理。
- 支持计算机绘图：LLM 会返回 `need_plot` / `safe_spec`，本地受控绘图器据此生成图像并插入 Word 报告。
- 支持公式排版：报告中的标记公式会转为 Word 公式对象，避免直接显示 LaTeX/Markdown 原文。
- 支持 Word 模板栏目：原始实验数据、实验数据处理、实验结果、不确定度计算、误差分析与课后思考题。
- 支持输出：`data/outputs/<run_id>/report.docx`。
- 支持追踪：每次运行生成 `input.normalized.json`、`compute.result.json`、`render.context.json`、`manifest.json`。

## 快速运行

无需安装依赖，直接运行：

```bash
python main.py
```

Windows 也可以直接运行：

```powershell
py -3 main.py
```

Linux 也可以直接运行：

```bash
python3 main.py
```

启动图形界面：

```bash
python main.py --ui
```

Windows / Linux 可分别使用：

```powershell
py -3 main.py --ui
```

```bash
python3 main.py --ui
```

如果你想在 CLI 中本地验证手动录入，并跳过 LLM 报告文字生成，可用：

```bash
python main.py --no-llm
```

注意：手写识别仍需要配置可用的 LLM API。

如果你想安装 UI 可选依赖：

```bash
pip install -e ".[ui]"
```

使用国内源安装 PySide6（Linux/macOS）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -e ".[ui]"
.venv/bin/python main.py --ui
```

使用国内源安装 PySide6（Windows PowerShell）：

```powershell
py -3 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -e ".[ui]"; .\.venv\Scripts\python.exe main.py --ui
```

现在 CLI 只提供两类生成入口：手动录入与手写识别；不再提供 JSON/CSV 输入入口。

## LLM 设置

进入交互界面后选择：

```text
1. 设置 API Key / Model
```

需要手动填写：

- `Base URL`：OpenAI 兼容接口地址，例如 `https://api.openai.com/v1`。
- `Model`：文本/视觉模型名，例如 `gpt-4o-mini` 或服务商提供的视觉模型。
- `API Key`：模型服务密钥。

设置保存在 `.phyexpassistant/settings.json`。

在 UI 模式下，这些设置也可以直接在界面左侧卡片中填写并保存。

如果你想把配置和输出放到别的位置，可以通过环境变量覆盖：

- `PHYEXPASSISTANT_HOME`：设置配置目录。
- `PHYEXPASSISTANT_OUTPUT_DIR`：设置输出目录。

这两个环境变量在 Windows 和 Linux 上都支持。

## 实验模板管理

实验模板文件位于 `src/phyexpassistant/resources/experiments/`，每个实验一个独立 `.json` 文件，例如 `exp_001.json`。单个模板至少包含 `id`、`name`、`category`、`description`、`report_mode` 和 `fields`；`fields` 中每个字段需要 `label`、`base_unit`、`accepted_units`，可选 `min` / `max` 作为校验范围。模板还可以添加 `formula_hints` 和 `table_hints`，用于把实验公式、表格结构和数据处理线索传给 LLM。程序运行时会自动把目录内多个模板聚合成内部 catalog。

UI 右侧“模板管理”页提供五类操作：

- `管理现有模板`：编辑模板目录的合并视图，支持重新载入、校验、格式化和保存；保存时会按实验 `id` 写回多个 `.json` 文件。
- `Agent OCR 新建模板`：选择多张包含实验公式、讲义页、空白表格或实验报告格式的图片，由视觉 LLM 直接返回单个实验模板对象，本地校验后追加到当前模板目录。
- `使用实验报告新建模板`：导入 `.pdf`、`.docx`、`.docm` 或 `.doc` 实验报告文件，本地提取可读文本后交给 LLM 抽象模板；纯图片扫描件可能需要先做文字识别。
- `直接粘贴导入模板`：粘贴完整模板目录合并 JSON、单个实验对象，或 `{ "experiment": {...} }` 后合并到当前草稿。
- `从 JSON 文件导入模板`：选择本地 JSON 文件并合并到当前模板草稿。

所有导入和 OCR 结果都会先在本地校验；无效模板不会写入文件。Agent OCR 和实验报告抽取都只返回单个实验对象，随后由本地合并到草稿，用户确认保存时写入模板目录。LLM 生成模板时只允许输出实验表格中的原始测量字段，不允许输出不确定度、误差、标准差或派生结果字段。图片模板抽取提示词在 `src/phyexpassistant/prompts/template_ocr.txt`，实验报告模板抽取提示词在 `src/phyexpassistant/prompts/template_report.txt`，报告正文生成提示词逻辑在 `src/phyexpassistant/llm_client.py` 的 `generate_report_content()`。

## 手写图片识别说明

当前版本暂时用多模态 LLM 直接做 OCR，不接入专用 OCR 引擎。流程是：

```text
图片 -> LLM 识别为结构化草稿 -> 用户确认 -> schema/单位/范围校验 -> 计算 -> docx
```

注意：LLM OCR 结果不是最终真值。识别结果会先回显给用户确认，手写识别报告以草稿中的 `student` 字段为学生信息来源；空值、非数字、行数不一致或超出合理范围都会阻止生成报告。识别结果预览表右侧可为每个识别字段单独启用 B 类不确定度，并在生成前写回草稿。
“手写识别”页顶部的“备注”只附加到图片识别 prompt，不会进入后续报告生成流程。
“报告生成备注”默认关闭；开启后备注只附加到报告内容生成 prompt，不参与 OCR，不进入 `normalized_input`，也不会作为固定正文写入 Word。

## B 类不确定度

每个数据字段都可以增加 `b_uncertainty` 属性，例如：

```json
"length": {
  "unit": "m",
  "values": [0.5, 0.6, 0.7],
  "b_uncertainty": {
    "enabled": true,
    "division": 0.001,
    "unit": "m",
    "method": "half_division_uniform"
  }
}
```

UI 的“手动录入”页顶部会显示学生信息区域，每个数据块都有“计算 B 类不确定度”复选框；“手写识别”页的识别结果预览表每一行也提供同样的 B 类不确定度控件。勾选后会显示分度值输入框和公式选择框。当前支持：

- `half_division_uniform`：`分度值 / (2√3)`，默认值。
- `division_uniform`：`分度值 / √3`。

程序会按所选公式估计该数据的 B 类标准不确定度，并传播到最终结果的合成不确定度中。

如果某个字段没有启用 `b_uncertainty`，报告中不会单独列出该字段的 B 类不确定度；如果所有字段都没有启用 B 类不确定度，报告只保留 A 类不确定度，不输出 B 类表项，也不进行矢量合成说明。

结果展示采用有效数字规则：不确定度默认保留 1 位有效数字，首位为 1 或 2 时保留 2 位；对应测量值会四舍五入到与不确定度一致的小数位。

手动录入页还提供“选择实验报告照片”栏目，允许你从本地选择一张照片；该文件不会进入 LLM prompt 或 OCR 处理，只在本地生成 Word 时作为“原始实验数据”照片展示。

生成的 Word 报告会把该照片放在“原始实验数据”栏目；OCR 或手动录入得到的数据表放在“实验数据处理”栏目；逐行公式与代入计算放在“实验结果”栏目；A/B/总不确定度与最终 `计算值 ± 不确定度` 放在“不确定度计算”栏目。



## 跨平台说明

- 路径解析已兼容 Windows 和 Linux，不依赖当前工作目录。
- 输入文件可以使用相对路径或绝对路径。
- 中文控制台输出会尽量切换到 UTF-8，减少 Windows 下乱码问题。
- 生成的 `.docx`、`manifest.json` 和中间文件都写在项目内或你指定的输出目录中。
- `--ui` 在 Windows 和 Linux 上都可用；若未安装 `PySide6`，程序会提示你安装可选依赖。
- UI 主界面已加入滚动区域，低分辨率或小窗口下可通过纵向/横向滚动访问全部控件。
- UI 左侧设置栏拥有独立纵向滚动条，输入框和按钮保持固定尺寸，不随窗口高度压缩。
- UI 会根据屏幕尺寸自动缩放字号、间距、控件尺寸，减少低分辨率下控件截断。
- UI 右上角 `设置` 可切换白色、深色和多组淡色主题，也支持自定义背景色和前景色。
- 日期选择器已替换为自定义扁平化控件，样式与主程序统一。

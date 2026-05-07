# Demo 架构说明

本 demo 对应 `项目可行性探索.md` 中的推荐方向：确定性工作流 + LLM 辅助 + 模板输出。

## 流程

```text
CLI 交互
  -> 设置 API Key / Model
  -> 读取手动输入或 LLM OCR 图片
  -> 标准化单位和字段
  -> LLM 生成报告文字与绘图计划
  -> 本地仅做安全绘图与文档渲染
  -> 构造 RenderContext
  -> 输出 report.docx 和 manifest.json
```

## 模块

- `src/phyexpassistant/cli.py`：用户交互界面。
- `src/phyexpassistant/ui.py`：PySide6 扁平化桌面 UI。
- `src/phyexpassistant/settings.py`：本地 LLM 设置读写。
- `src/phyexpassistant/llm_client.py`：OpenAI 兼容 Chat Completions 调用，包含图片 OCR demo。
- `src/phyexpassistant/workflow.py`：输入标准化、LLM 报告编排、安全绘图调度、产物写入。
- `src/phyexpassistant/docx_writer.py`：无第三方依赖的最小 `.docx` 生成器。
- `src/phyexpassistant/experiments.py`：demo 题库注册。

## 边界

- LLM 负责实验专属报告内容和绘图计划，但本地不执行 LLM 返回的代码。
- LLM 需要用 `{{LaTeXbegin}}...{{LaTeXend}}` 标记可渲染的 LaTeX 公式，本地 Word 渲染器会将其转为 Office Math。
- Word 报告模板按“原始实验数据 -> 实验数据处理 -> 实验结果 -> 不确定度计算 -> 误差分析/课后思考题”的顺序组织。
- “原始实验数据”展示手动页选择的实验报告照片或 OCR 原图；“实验结果”展示逐行公式和脱式计算；“不确定度计算”展示 A 类、B 类和总不确定度。
- “手写识别”页顶部的“备注”只会附加到 OCR prompt，不会进入后续报告生成请求。
- “报告生成备注”开关默认关闭；启用后只会附加到报告内容生成 prompt，不进入 OCR prompt、`normalized_input` 或固定 Word 正文。
- 计算机绘图只接受 `need_plot` / `safe_spec`，并由本地白名单绘图器生成图片。
- 每次运行都生成独立 `run_id` 目录。
- API Key 只保存在本地忽略目录，不写入 `manifest.json`。

## Windows / Linux 适配

- 项目根目录由 `src/phyexpassistant/paths.py` 根据代码位置自动推导，不依赖运行命令所在目录。
- 图片路径支持绝对路径，也支持相对于当前目录或项目根目录的相对路径。
- 默认配置目录为 `.phyexpassistant/`，可用 `PHYEXPASSISTANT_HOME` 覆盖。
- 默认输出目录为 `data/outputs/`，可用 `PHYEXPASSISTANT_OUTPUT_DIR` 覆盖。
- 控制台输出会尝试使用 UTF-8，降低 Windows 中文显示问题。
- UI 模式通过 `--ui` 启动，默认仍是 CLI；若缺少 `PySide6`，会提示安装可选依赖而不是直接崩溃。
- UI 主内容使用 `QScrollArea`，小屏幕下保留滚动条，避免低分辨率设备上控件被挤出窗口。
- 左侧设置栏单独使用 `QScrollArea`，只做纵向滚动，避免 LLM 设置、输出选项和快捷操作等控件被压缩。
- UI 根据屏幕可用尺寸计算缩放系数，用于窗口尺寸、字体、间距、按钮和滚动条；学生信息位于“手动录入”页顶部，OCR 报告以识别草稿中的 `student` 字段为准。
- 手动录入页提供“选择实验报告照片”本地文件选择栏，该文件不进入 LLM prompt 或 OCR 处理，只在本地 Word 渲染时展示。
- UI 主题由本地设置持久化，预置白色、深色、薄荷、薰衣草、暖杏，并支持自定义背景色与前景色。
- 日期选择器使用自定义 `FlatDatePicker`，不依赖系统原生日期控件样式。
- 数据字段支持 `b_uncertainty` 属性。手动录入块和 OCR 预览表行都可启用该属性，启用后记录仪器分度值和计算公式，可在 `分度值/(2√3)` 与 `分度值/√3` 间切换，并交由报告生成流程按模板处理。

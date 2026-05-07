# Demo 架构说明

本 demo 对应 `项目可行性探索.md` 中的推荐方向：确定性工作流 + LLM 辅助 + 模板输出。

## 流程

```text
CLI 交互
  -> 设置 API Key / Model
  -> 读取 JSON、CSV、手动输入或 LLM OCR 图片
  -> 标准化单位和字段
  -> 单摆实验计算
  -> LLM 生成报告文字，不改数值
  -> 构造 RenderContext
  -> 输出 report.docx 和 manifest.json
```

## 模块

- `src/phyexpassistant/cli.py`：用户交互界面。
- `src/phyexpassistant/ui.py`：PySide6 扁平化桌面 UI。
- `src/phyexpassistant/settings.py`：本地 LLM 设置读写。
- `src/phyexpassistant/llm_client.py`：OpenAI 兼容 Chat Completions 调用，包含图片 OCR demo。
- `src/phyexpassistant/workflow.py`：输入校验、单位标准化、计算、产物写入。
- `src/phyexpassistant/docx_writer.py`：无第三方依赖的最小 `.docx` 生成器。
- `src/phyexpassistant/experiments.py`：demo 题库注册。

## 边界

- LLM 可以识别图片和生成文字，但不能覆盖计算结果。
- 计算只使用标准化后的数据。
- 每次运行都生成独立 `run_id` 目录。
- API Key 只保存在本地忽略目录，不写入 `manifest.json`。

## Windows / Linux 适配

- 项目根目录由 `src/phyexpassistant/paths.py` 根据代码位置自动推导，不依赖运行命令所在目录。
- JSON、CSV、图片路径支持绝对路径，也支持相对于当前目录或项目根目录的相对路径。
- 默认配置目录为 `.phyexpassistant/`，可用 `PHYEXPASSISTANT_HOME` 覆盖。
- 默认输出目录为 `data/outputs/`，可用 `PHYEXPASSISTANT_OUTPUT_DIR` 覆盖。
- 控制台输出会尝试使用 UTF-8，降低 Windows 中文显示问题。
- UI 模式通过 `--ui` 启动，默认仍是 CLI；若缺少 `PySide6`，会提示安装可选依赖而不是直接崩溃。
- UI 主内容使用 `QScrollArea`，小屏幕下保留滚动条，避免低分辨率设备上控件被挤出窗口。
- 左侧设置栏单独使用 `QScrollArea`，只做纵向滚动，避免 LLM 设置、学生信息、输出选项等控件被压缩。
- UI 根据屏幕可用尺寸计算缩放系数，用于窗口尺寸、字体、间距、按钮和滚动条。
- UI 主题由本地设置持久化，预置白色、深色、薄荷、薰衣草、暖杏，并支持自定义背景色与前景色。
- 日期选择器使用自定义 `FlatDatePicker`，不依赖系统原生日期控件样式。
- 数据字段支持 `b_uncertainty` 属性。启用后以仪器分度值计算 B 类标准不确定度，可在 `分度值/(2√3)` 与 `分度值/√3` 间切换，并通过灵敏度系数传播到最终结果。

# Repository Guidelines

## 项目结构与模块组织

本仓库是基于 `src` 布局的 Python 3.10+ 项目。核心包位于 `src/phyexpassistant/`，其中 `cli.py` 提供命令行入口，`ui.py` 提供图形界面，`workflow.py` 编排数据校验、计算与报告生成流程。`docx_writer.py` 负责 Word 模板渲染、原始照片插入和 LaTeX 公式标记解析。实验定义和资源放在 `src/phyexpassistant/resources/`，提示词放在 `src/phyexpassistant/prompts/`，图标等静态资源放在 `src/phyexpassistant/assets/`。用户生成入口限定为手动录入与手写识别；模板管理位于 UI 右侧“模板管理”页，底层文件为 `src/phyexpassistant/resources/experiments/*.json`，模板抽取提示词包括 `template_ocr.txt` 与 `template_report.txt`。运行产物默认写入 `data/outputs/<run_id>/`。项目说明和设计文档位于 `README.md` 与 `docs/`。

## 构建、测试与开发命令

- `python main.py`：直接启动交互式 CLI，无需安装包。
- `python main.py --no-llm`：启动交互式 CLI；手动录入生成报告时跳过 LLM 报告文字生成。
- `python main.py --ui`：启动 PySide6 图形界面；需要安装 UI 可选依赖。
- `python -m pip install -e ".[ui]"`：以可编辑模式安装项目及 UI 依赖。

## 编码风格与命名约定

遵循现有 Python 风格：4 空格缩进，函数和模块使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。优先使用类型标注、`dataclass` 和小型纯函数保持计算逻辑可读。资源文件使用语义化名称，例如 `experiments/exp_001.json`、`plot_plan.txt`。修改实验模板时保持单实验 JSON 对象格式，并通过 `normalize_experiment_catalog()` / UI 校验后再保存。不要把生成的 `.docx`、运行中间文件或本地配置提交到仓库。

## 测试指南

当前仓库未配置正式测试框架。修改计算、解析或报告生成逻辑后，至少运行 `python main.py --no-llm`，通过 CLI 手动录入一组最小数据并生成报告；涉及 UI 时同时启动 `python main.py --ui` 做界面冒烟检查；涉及 Word 模板时额外确认原始实验数据、实验数据处理、实验结果和不确定度计算等栏目正确输出。新增测试时建议使用 `pytest`，测试文件放在 `tests/`，命名为 `test_<module>.py`，用例覆盖正常路径、输入校验失败和边界数值。

## 提交与 Pull Request 规范

Git 历史使用简短英文提交信息，例如 `Add application icon`、`Refine UI and LLM plotting workflow`。保持祈使句或动词开头，单次提交聚焦一个主题。Pull Request 应说明变更目的、主要影响范围、验证命令；涉及 UI 或报告输出时附截图或示例产物路径；关联 issue 时在描述中注明。

## 安全与配置提示

不要提交 `.phyexpassistant/settings.json`、API Key 或真实实验隐私数据。可用 `PHYEXPASSISTANT_HOME` 覆盖配置目录，用 `PHYEXPASSISTANT_OUTPUT_DIR` 覆盖输出目录。处理 LLM 或 OCR 结果时保留用户确认与 schema 校验流程，避免直接信任模型输出。保持 UI 备注分流：OCR 备注只传给 `extract_handwritten_data()`，报告生成备注只传给 `generate_report_content()`，不要写入 `normalized_input` 或固定 Word 正文。

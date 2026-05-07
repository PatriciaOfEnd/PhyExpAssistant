# LLM 绘图调用方案

当前 demo 已实现确定性本地绘图：单摆实验会生成 `figures/pendulum_fit.png`，并插入到 Word 报告的“计算公式”和“计算结果”之后。

后续扩展更多实验时，建议采用“LLM 只做绘图规划，本地执行受控绘图”的方案。

## 推荐流程

```text
ComputeResult
  -> LLM Plot Planner
  -> plot_plan.json
  -> 本地校验 safe_spec
  -> 本地绘图器生成 PNG
  -> 写入 compute_result.figures
  -> Word Renderer 插入图片
```

## JSON 协议

```json
{
  "need_plot": true,
  "plots": [
    {
      "key": "pendulum_fit",
      "title": "T²-L 线性拟合图",
      "position": "after_calculation_results",
      "safe_spec": {
        "plot_type": "scatter_with_linear_fit",
        "x": {"source": "normalized_input.data.length_m", "label": "L / m"},
        "y": {"source": "computed.period_squared", "label": "T² / s²"},
        "fit": {"source": "compute_result.fit", "enabled": true}
      },
      "python_code_required": false,
      "python_code": null
    }
  ]
}
```

## Python 代码模式

可以保留 `python_code` 作为高级模式，但不建议直接执行 LLM 原始代码。更安全的做法是：

- 优先使用 `safe_spec` 映射到本地绘图函数。
- 若必须执行 Python 代码，只允许 `draw(data, output_path)` 函数。
- 使用 AST 检查禁止 `os`、`subprocess`、`socket`、`requests`、`open` 等危险能力。
- 放入隔离子进程执行，限制超时和输出目录。
- 执行后只接受 PNG/JPEG/SVG 等明确文件类型。

## 插图位置

推荐统一插入到：

```text
三、实验数据处理
  1. 计算公式
  2. 计算结果
  3. 计算机绘图
```

这样与 `train/` 下样例报告的“数据处理 -> 图像/拟合 -> 结果分析”结构一致。

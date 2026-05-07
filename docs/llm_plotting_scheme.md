# LLM 绘图调用方案

当前 demo 采用“LLM 先判断是否需要绘图，再给出受控 `safe_spec`，本地绘图器只执行白名单绘图”的方案。

## 流程

```text
标准化输入
  -> LLM 报告内容生成
  -> LLM 绘图计划生成（need_plot + safe_spec）
  -> 本地校验 safe_spec
  -> 本地受控绘图器生成 PNG
  -> 写入 report figures
  -> Word Renderer 插入图片
```

## JSON 协议

```json
{
  "need_plot": true,
  "reason": "需要绘图的原因",
  "safe_spec": {
    "plots": [
      {
        "key": "plot_1",
        "title": "图标题",
        "caption": "图注",
        "description": "说明横轴、纵轴和主要趋势",
        "position": "after_calculation_results",
        "plot_type": "scatter_with_linear_fit",
        "x": {
          "source": "normalized_input.data.field_a.values",
          "label": "x 轴名称",
          "transform": "identity"
        },
        "y": {
          "source": "normalized_input.data.field_b.values",
          "label": "y 轴名称",
          "transform": "square"
        },
        "fit": {"enabled": true, "kind": "linear"}
      }
    ]
  },
  "warnings": []
}
```

## 约束

- `need_plot` 为 `false` 时，`safe_spec.plots` 必须为空。
- `plot_type` 只允许：`scatter`、`line`、`scatter_with_linear_fit`、`bar`。
- `source` 只允许引用 `normalized_input` 中已有数据。
- `transform` 只允许：`identity`、`square`、`sqrt`、`abs`、`log10`、`none`。
- 不返回 Python 代码，不执行 LLM 代码。
- 最多返回 3 张图。

## 插图位置

推荐统一插入到“实验数据处理”部分，放在公式和结果表之后。

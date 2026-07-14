# Profile：LaTeX 构建与版本溯源

## 启用条件

仅当用户要求检查 LaTeX 工程、编译、路径、Git、提交包或源码/PDF 对应关系时启用。

## 活动源码

- 明确主文件，优先显式传入 `--main main.tex`。
- 按 `\input`、`\include`、`\subfile`、`\import` 等递归识别活动源码，只在活动依赖图内检查 label、citation、草稿标记和图表对象。
- 按 `\bibliography`、`\addbibresource` 识别活动 `.bib`；未启用的旧 `.bib` 不得掩盖缺失键。
- 条件编译或宏展开无法解析时标为覆盖不确定，不作确定错误。
- 优先结合当前完整编译的 `.log`/`.blg` 核对 undefined reference/citation。

## 工程与溯源

- 按需记录仓库、分支、提交和 dirty 状态，防止审错版本；无 Git 时不构成问题。
- 检查活动图片路径、`\graphicspath`、扩展名和大小写。宏路径无法静态解析时标为 `not_verified`。
- 绝对路径、宏包冲突和文件名可移植性仅在构建/交付场景报告。
- 未跟踪的 `.aux/.toc/.log` 等普通辅助文件只计数，不逐个产生问题；仅当被版本库跟踪或混入提交包时报告。

## 工具

```bash
python3 scripts/scan_latex_thesis.py /path/to/project --main main.tex
```

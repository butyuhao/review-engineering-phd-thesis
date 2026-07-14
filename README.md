# 中文工科博士论文审查 Skill

本 Skill 默认审查完整初稿的学术论证质量：先建立论文自己的贡献和术语映射，再按算法、系统、实验、理论或应用范式核查“问题—方法—证据—结论—边界”。它不要求固定章节结构、贡献数量一一对应或中英文摘要逐句翻译。

## 分层结构

```text
SKILL.md
shared/
  core-checklist.md
  severity-rules.md
  report-template.md
  paradigms/
    algorithm-model.md
    system-hardware.md
    experiment-process.md
    theory-modeling.md
    application-interdisciplinary.md
profiles/
  final-pdf.md
  latex-build-and-provenance.md
  blind-review.md
  migration-audit.md
  degree-materials.md
scripts/
  scan_latex_thesis.py
  scan_pdf_text.py
```

默认只加载核心清单、严重度规则、报告模板和与各贡献相关的范式。最终 PDF、LaTeX/Git、盲审、迁移残留和学位材料仅在请求需要时加载 profile，避免低价值工程告警淹没学术问题。

## 状态与严重度

自动扫描只输出：

- `candidate`：规则命中，待核实；
- `not_verified`：工具或输入不足。

核对活动源码、当前编译/PDF、原始结果或权威来源后，才能将 `confirmed` 项定为 P0-P3。扫描候选优先级不等于论文严重度。

## LaTeX 扫描

```bash
python3 scripts/scan_latex_thesis.py /path/to/thesis --main main.tex
python3 scripts/scan_latex_thesis.py /path/to/thesis --main main.tex --term '旧术语=新术语'
python3 scripts/scan_latex_thesis.py /path/to/thesis --main main.tex --check-provenance --json
```

扫描器从主文件递归解析 `\input`、`\include`、`\subfile` 和 `\import`，只检查活动源码及活动 bibliography。它支持 `\graphicspath` 和 `\DeclareGraphicsExtensions`；无法展开的宏和条件编译标为 `not_verified`。未跟踪的普通辅助文件只计数，不产生 finding。

## PDF 扫描

```bash
python3 scripts/scan_pdf_text.py /path/to/thesis.pdf
python3 scripts/scan_pdf_text.py /path/to/thesis.pdf --expected-page-size A4
python3 scripts/scan_pdf_text.py /path/to/thesis.pdf --sha256 --json
```

未提供学校期望尺寸时只报告观测尺寸，不判断 A4 合规性。乱码属于文本层候选，必须视觉确认；低文本页只提供抽查导航。“PDF 可提取文本量估计”不得作为学校、Word、`texcount` 或查重系统字数。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖活动依赖图、未加载旧文件、活动 bibliography、`\graphicspath`、宏路径覆盖缺口、PDF 尺寸参数化和候选状态模型。

## 局限

- 静态解析无法完整执行 TeX 宏和条件分支；应结合 `.fls/.log/.blg` 与当前 PDF。
- 文本提取无法确认裁切、超宽、颜色、字号或视觉乱码。
- 自动工具不能判断创新性、实验公平性、因果性和学科贡献，正式报告必须人工核实证据。

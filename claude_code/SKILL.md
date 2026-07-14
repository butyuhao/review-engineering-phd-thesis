---
name: review-engineering-phd-thesis
description: 审查已有完整初稿的中文工科博士论文，默认聚焦研究主线、贡献可追溯性、证据、复现、主张边界、术语和学术对象；终稿 PDF、LaTeX/Git、盲审、模板迁移及学位材料仅按需启用。
---

# 检查中文工科博士论文

## 默认规则

每次审查读取：

- `../shared/core-checklist.md`
- `../shared/severity-rules.md`
- `../shared/report-template.md`

再按每项贡献的证据类型，只读取 `../shared/paradigms/` 中相关文件。不要按学院名称统一套用要求。

## 按需 Profile

仅在用户明确需要时读取：

- PDF/提交版：`../profiles/final-pdf.md`
- LaTeX、构建、Git、路径：`../profiles/latex-build-and-provenance.md`
- 盲审：`../profiles/blind-review.md`
- 迁移残留：`../profiles/migration-audit.md`
- 学位与成果材料：`../profiles/degree-materials.md`

## 工作流

1. 记录实际审查对象、目标和证据边界，不强制 Git 或最终 PDF。
2. 为核心贡献建立“问题—研究实体—证据—结论—边界—位置”映射，允许跨章、合并、顺序和长短名称差异。
3. 按算法、系统、实验、理论、应用等范式检查相应证据，不强制固定章节结构。
4. 有 LaTeX 时优先运行 `python3 ../scripts/scan_latex_thesis.py /path/to/project --main main.tex`；有 PDF 且学校明确要求时再传 `--expected-page-size`。
5. 自动结果只标 `candidate` 或 `not_verified`。核对活动源码、编译/PDF、原始结果或权威来源后，才能将 `confirmed` 项定为 P0-P3。
6. 使用共享报告模板，先列确认的重大问题，再列候选与未验证项；每项说明位置、证据、影响、最小修改和验证动作。

## 边界

- 不强制贡献数量/顺序/名称一一相同，也不要求中英文摘要按句对齐。
- 不把句长、连接词、标题形式、caption 标点或章节模板偏好当成确定错误。
- 消融、归因、相关和敏感性结果不自动等同于因果或机理证明。
- 模型裁判、模拟对象和普通标注者不写成真人或领域专家。
- 未执行的视觉、外部事实、实验和匿名检查必须标为未验证。

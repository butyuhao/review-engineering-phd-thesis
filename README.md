# 中文工科博士论文审查 Skill

`review-engineering-phd-thesis` 是一个面向中文工科博士学位论文初稿与终稿的提交前审查仓库。它适用于计算机、电子信息、自动化、机械、土木、材料、能源、环境、生物医学工程等方向，也支持算法、系统、实验、理论和交叉应用混合型论文。

本项目的核心原则是：**先提取论文自己的局部标准，再检查全文是否一致地遵守这些标准。** 自动扫描只定位机械风险，最终结论必须结合论文源码、编译 PDF、研究范式和证据链人工判断。

## 能检查什么

- 研究问题、挑战、贡献、框架图、章标题和总结是否一一对应。
- 中文与英文摘要的贡献、数字、术语和结论是否逐句对齐。
- 章节结构、理论基础、相关工作、方法、实验和结论是否形成闭环。
- 不同研究范式是否提供了匹配的证据，例如算法基线、系统指标、实验重复性、理论假设或真实用户验证。
- 术语、符号、缩写、图表、公式、算法、caption、浮动体和交叉引用是否统一。
- 引用是否贴近对应论断，参考文献、政策、标准和出版状态是否可靠。
- 最终 PDF 是否存在非 A4 页面、乱码、未解析引用、异常空白页、超宽图表或盲审信息泄漏。
- 字数统计口径和学位申请、导师评语、成果清单等行政材料是否准确。

## 仓库结构

```text
review-engineering-phd-thesis/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── README.md
├── shared/
│   ├── checklist.md
│   ├── discipline-adaptation.md
│   ├── severity-rules.md
│   └── report-template.md
├── claude_code/
│   └── SKILL.md
├── scripts/
│   ├── scan_latex_thesis.py
│   └── scan_pdf_text.py
├── tests/
│   └── fixtures/
└── examples/
```

`shared/` 是唯一的审查规则来源。Codex 和 Claude Code 的 `SKILL.md` 只定义平台工作流并引用共享规则，避免维护两套相互漂移的 checklist。

## 安装与触发

### Codex

仓库根目录本身就是标准 Codex skill，可直接安装或链接到 Codex 的 skills 目录。根目录 `SKILL.md` 会按需读取 `shared/` 中的详细规则。

典型触发语句：

- “检查这篇中文工科博士论文是否可以提交。”
- “核对中英文摘要、框架图和各章贡献是否一致。”
- “检查图表、公式、引用、盲审信息和最终 PDF 排版。”

### Claude Code

将 `claude_code/SKILL.md` 配置为项目或用户级 skill，并确保它能够读取同仓库的 `shared/` 和 `scripts/`。

## 推荐工作流

1. 锁定当前论文项目、最新源码和最新编译 PDF，避免误审旧模板或旧版本。
   若使用 Git，同时记录远程仓库、分支和提交号；远程不可访问时明确本次仅核查的本地副本。
2. 从论文中提取“局部标准表”：中英文标题、研究主线、问题、贡献、章标题、术语、符号、方法、数据、指标和格式惯例。
3. 为每个研究贡献判断研究范式；混合论文可为不同章节分别标注。
4. 运行机械扫描，收集乱码、标签、引用、caption、草稿标记和页面风险。
5. 按共享 checklist 完成人工逻辑审查和 PDF 视觉抽查。
6. 按 P0-P3 输出发现；每项包含位置、证据、影响、修改建议和验证方式。
7. 修改后清理旧辅助文件，完整编译、重跑扫描并检查受影响的 PDF 页面。

## 脚本用法

两个脚本只依赖 Python 标准库。PDF 扫描需要系统可用的 `pdfinfo` 和 `pdftotext`（通常由 Poppler 提供）。

### LaTeX 项目

```bash
python3 scripts/scan_latex_thesis.py /path/to/thesis
python3 scripts/scan_latex_thesis.py /path/to/thesis --term '旧术语=新术语'
python3 scripts/scan_latex_thesis.py /path/to/thesis --terms-file terms.json --json
```

`terms.json` 示例：

```json
{
  "组件": "节点",
  "旧方法名": "正式方法名"
}
```

扫描包括：乱码、草稿/占位文本、空 TeX 文件、重复章标题、图片路径、引号、重复或缺失 label、缺失 bib key、未引用主要图表、caption 格式与末尾标点混用、`paragraph` 标点混用、旧术语残留，以及可能混入提交包的辅助文件和 macOS 伪文件。

### 最终 PDF

```bash
python3 scripts/scan_pdf_text.py /path/to/thesis.pdf
python3 scripts/scan_pdf_text.py /path/to/thesis.pdf --low-text-threshold 30 --json
```

扫描包括：页数与 A4 尺寸、乱码、`??`、草稿标记、低文本页，并给出“中文字符数 + 拉丁/数字词元数”的 Word-like 近似字数。该数字不等于 Word、LaTeX `texcount` 或学校查重系统的官方口径。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试仅使用 Python 标准库，fixtures 同时覆盖材料实验论文和土木理论建模论文，防止检查器退化为计算机论文专用规则。

## 局限

- 正则扫描不能理解 LaTeX 的全部宏展开、条件编译和复杂自定义环境。
- “未引用图表”只能依据可解析的 `label/ref` 判断，不能识别正文中的手写编号。
- PDF 文本提取可能重复页眉页脚，扫描型 PDF 或字体映射异常时字数会失真。
- 低文本页可能是封面、章间空白页或整页图片，必须视觉确认。
- 自动工具不能判断创新性、实验是否公平、机制解释是否成立，也不能替代学科专家意见。
- 盲审信息是否合规取决于学校当年规则；发现异常后需核对编译开关和官方通知。

## 维护原则

- 通用规则只写入 `shared/`，平台入口不复制 checklist。
- 新增检查项时说明适用研究范式、严重度和误报边界。
- 外部事实（政策、标准、论文出版状态、会议期刊信息）必须基于权威来源核实。
- 临近提交时优先报告影响评审、答辩和行政受理的问题，避免用低价值润色淹没作者。

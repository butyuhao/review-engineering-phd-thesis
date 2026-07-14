#!/usr/bin/env python3
"""Scan the active source graph of a dissertation LaTeX project.

The scanner emits candidates and coverage gaps, never confirmed P0-P3 findings.
It uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


SKIP_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "build",
    "dist",
    "node_modules",
    "paper_for_reference",
    "papers_for_reference",
    "reference_papers",
}

PROJECT_ARTIFACT_NAMES = {".DS_Store"}
PROJECT_ARTIFACT_SUFFIXES = (
    ".aux",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".lof",
    ".log",
    ".lot",
    ".out",
    ".synctex.gz",
    ".toc",
)

DRAFT_PATTERNS = {
    "TODO": re.compile(r"\bTODO\b", re.IGNORECASE),
    "FIXME": re.compile(r"\bFIXME\b", re.IGNORECASE),
    "TBD": re.compile(r"\bTBD\b", re.IGNORECASE),
    "DRAFT": re.compile(r"(?im)^\s*DRAFT(?:\s*[:：].*)?\s*$"),
    "XXX": re.compile(r"\bXXX\b"),
    "待补": re.compile(r"待补(?:充|写|引用|实验|数据)?"),
    "待定": re.compile(r"待定"),
    "占位文本": re.compile(r"(?:这里写|此处(?:填写|补充|插入)|待完善)"),
}

GARBLED_PATTERNS = {
    "�": "Unicode 替换字符",
    "锟斤拷": "常见中文乱码序列“锟斤拷”",
    "Ã": "疑似 UTF-8/Latin-1 乱码片段“Ã”",
    "â€": "疑似标点乱码片段“â€”",
}

DEFAULT_GRAPHICS_EXTENSIONS = ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class Finding:
    check_id: str
    status: str
    priority: str
    confidence: str
    requires_confirmation: bool
    suggested_severity: str
    path: str
    line: int
    message: str
    possible_false_positive: str
    confirmation_action: str

    @property
    def code(self) -> str:
        """Compatibility alias for older callers."""
        return self.check_id


def strip_comments(text: str) -> str:
    """Remove unescaped LaTeX comments while preserving line numbers."""
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        cut = len(line)
        for index, char in enumerate(line):
            if char != "%":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                cut = index
                break
        fragment = line[:cut]
        if line.endswith("\n") and not fragment.endswith("\n"):
            fragment += "\n"
        output.append(fragment)
    return "".join(output)


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def display_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def source_files(root: Path, suffix: str) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob(f"*{suffix}"):
        relative_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in relative_parts[:-1]):
            continue
        if path.name.startswith("._"):
            continue
        found.append(path.resolve())
    return sorted(found)


def project_artifacts(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in relative_parts[:-1]):
            continue
        if (
            path.name.startswith("._")
            or path.name in PROJECT_ARTIFACT_NAMES
            or path.name.endswith(PROJECT_ARTIFACT_SUFFIXES)
        ):
            found.append(path.resolve())
    return sorted(found)


def git_repository_state(root: Path) -> dict[str, object] | None:
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if Path(top).resolve() != root.resolve():
            return None
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return {"branch": branch or "DETACHED", "head": head, "dirty": bool(status.strip())}


def git_tracked_files(root: Path) -> set[str]:
    if git_repository_state(root) is None:
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return set()
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    }


def add(
    findings: list[Finding],
    root: Path,
    *,
    check_id: str,
    path: Path,
    line: int,
    message: str,
    priority: str = "medium",
    confidence: str = "medium",
    status: str = "candidate",
    suggested_severity: str = "P2",
    possible_false_positive: str = "需要结合活动版本和上下文判断。",
    confirmation_action: str = "核对活动源码上下文和当前编译结果。",
) -> None:
    findings.append(
        Finding(
            check_id=check_id,
            status=status,
            priority=priority,
            confidence=confidence,
            requires_confirmation=True,
            suggested_severity=suggested_severity,
            path=display_path(path, root),
            line=line,
            message=message,
            possible_false_positive=possible_false_positive,
            confirmation_action=confirmation_action,
        )
    )


def parse_term_values(values: Iterable[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"术语映射 {value!r} 无效，应为 OLD=NEW")
        old, new = value.split("=", 1)
        if not old:
            raise ValueError("旧术语不能为空")
        pairs.append((old, new))
    return pairs


def load_terms_file(path: Path | None) -> list[tuple[str, str]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [(str(old), str(new)) for old, new in data.items()]
    if isinstance(data, list):
        pairs: list[tuple[str, str]] = []
        for item in data:
            if not isinstance(item, dict) or "old" not in item or "new" not in item:
                raise ValueError("术语文件列表项必须包含 old 和 new")
            pairs.append((str(item["old"]), str(item["new"])))
        return pairs
    raise ValueError("术语文件必须是 JSON 对象或 {old,new} 对象列表")


def extract_braced(text: str, open_brace: int) -> tuple[str, int] | None:
    if open_brace >= len(text) or text[open_brace] != "{":
        return None
    depth = 0
    escaped = False
    for index in range(open_brace, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1 : index], index + 1
    return None


def resolve_file(reference: str, current: Path, root: Path, suffix: str) -> Path | None:
    value = reference.strip()
    if not value or any(token in value for token in ("\\", "#")):
        return None
    target = Path(value)
    candidates: list[Path] = []
    if target.is_absolute():
        candidates.append(target)
    else:
        candidates.extend((current.parent / target, root / target))
    for candidate in candidates:
        if candidate.suffix:
            resolved = candidate.resolve()
        else:
            resolved = Path(f"{candidate}{suffix}").resolve()
        if resolved.is_file():
            return resolved
    candidate = candidates[0]
    return (candidate if candidate.suffix else Path(f"{candidate}{suffix}")).resolve()


def detect_main(root: Path, explicit: Path | None) -> tuple[Path, str | None]:
    if explicit is not None:
        path = explicit if explicit.is_absolute() else root / explicit
        path = path.resolve()
        if not path.is_file():
            raise ValueError(f"主文件不存在：{path}")
        return path, None

    tex_files = source_files(root, ".tex")
    document_roots: list[Path] = []
    for path in tex_files:
        text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        if re.search(r"\\documentclass(?:\[[^\]]*\])?\s*\{", text):
            document_roots.append(path)
    preferred = (root / "main.tex").resolve()
    if preferred in document_roots:
        note = None if len(document_roots) == 1 else f"检测到 {len(document_roots)} 个 documentclass 文件，按约定选择 main.tex"
        return preferred, note
    if len(document_roots) == 1:
        return document_roots[0], None
    if preferred.is_file():
        return preferred, "未检测到唯一 documentclass，按约定选择 main.tex"
    if len(tex_files) == 1:
        return tex_files[0], "未检测到 documentclass，选择项目中唯一 TeX 文件"
    raise ValueError("无法可靠识别主文件，请使用 --main main.tex")


def active_source_graph(root: Path, main: Path) -> tuple[list[Path], list[tuple[Path, int, str]]]:
    include_re = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")
    import_re = re.compile(r"\\(?:import|subimport|inputfrom|includefrom)\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
    active: list[Path] = []
    unresolved: list[tuple[Path, int, str]] = []
    visited: set[Path] = set()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in visited:
            return
        visited.add(resolved)
        active.append(resolved)
        text = strip_comments(resolved.read_text(encoding="utf-8", errors="replace"))
        dependencies: list[tuple[int, str]] = []
        for match in include_re.finditer(text):
            values = match.group(1).split(",") if match.group(0).lstrip().startswith("\\include") else [match.group(1)]
            dependencies.extend((line_number(text, match.start()), value) for value in values)
        for match in import_re.finditer(text):
            dependencies.append((line_number(text, match.start()), str(Path(match.group(1)) / match.group(2))))
        for line, reference in dependencies:
            candidate = resolve_file(reference, resolved, root, ".tex")
            if candidate is None or not candidate.is_file():
                unresolved.append((resolved, line, reference.strip()))
                continue
            visit(candidate)

    visit(main)
    return active, unresolved


def active_bibliographies(
    root: Path,
    sources: dict[Path, str],
) -> tuple[list[Path], list[tuple[Path, int, str]]]:
    bibliography_re = re.compile(r"\\bibliography\s*\{([^{}]+)\}")
    add_resource_re = re.compile(r"\\addbibresource\s*(?:\[[^\]]*\]\s*)?\{([^{}]+)\}")
    active: list[Path] = []
    unresolved: list[tuple[Path, int, str]] = []
    seen: set[Path] = set()
    for path, text in sources.items():
        references: list[tuple[int, str]] = []
        for match in bibliography_re.finditer(text):
            references.extend((line_number(text, match.start()), value) for value in match.group(1).split(","))
        for match in add_resource_re.finditer(text):
            references.append((line_number(text, match.start()), match.group(1)))
        for line, reference in references:
            candidate = resolve_file(reference, path, root, ".bib")
            if candidate is None or not candidate.is_file():
                unresolved.append((path, line, reference.strip()))
                continue
            if candidate not in seen:
                seen.add(candidate)
                active.append(candidate)
    return active, unresolved


def collect_graphics_configuration(
    root: Path,
    sources: dict[Path, str],
) -> tuple[list[Path], tuple[str, ...]]:
    paths: list[Path] = []
    seen_paths: set[Path] = set()
    extensions: list[str] = []
    graphicspath_re = re.compile(r"\\graphicspath\s*(\{)")
    extension_re = re.compile(r"\\DeclareGraphicsExtensions\s*\{([^{}]+)\}")
    for source, text in sources.items():
        for match in graphicspath_re.finditer(text):
            extracted = extract_braced(text, match.start(1))
            if not extracted:
                continue
            content, _ = extracted
            for value in re.findall(r"\{([^{}]+)\}", content):
                if any(token in value for token in ("\\", "#")):
                    continue
                declared = Path(value)
                bases = [declared] if declared.is_absolute() else [source.parent / declared, root / declared]
                for base in bases:
                    resolved = base.resolve()
                    if resolved not in seen_paths:
                        seen_paths.add(resolved)
                        paths.append(resolved)
        for match in extension_re.finditer(text):
            for value in match.group(1).split(","):
                extension = value.strip()
                if extension and extension not in extensions:
                    extensions.append(extension if extension.startswith(".") else f".{extension}")
    return paths, tuple([""] + extensions) if extensions else DEFAULT_GRAPHICS_EXTENSIONS


def graphics_candidates(
    root: Path,
    tex_path: Path,
    raw_target: str,
    graphics_paths: list[Path] | None = None,
    extensions: tuple[str, ...] = DEFAULT_GRAPHICS_EXTENSIONS,
) -> list[Path]:
    target = Path(raw_target.strip())
    if target.is_absolute():
        bases = [target]
    else:
        bases = [tex_path.parent / target, root / target]
        bases.extend(path / target for path in (graphics_paths or []))
    candidates: list[Path] = []
    for base in bases:
        if base.suffix:
            candidates.append(base.resolve())
        else:
            candidates.extend(Path(f"{base}{extension}").resolve() for extension in extensions)
    return list(dict.fromkeys(candidates))


def unmatched_punctuation_line(text: str, left: str, right: str) -> int | None:
    stack: list[int] = []
    for offset, char in enumerate(text):
        if char == left:
            stack.append(offset)
        elif char == right:
            if stack:
                stack.pop()
            else:
                return line_number(text, offset)
    return line_number(text, stack[-1]) if stack else None


def scan_project(
    root: Path,
    term_pairs: list[tuple[str, str]] | None = None,
    main: Path | None = None,
    check_provenance: bool = False,
) -> tuple[list[Finding], dict[str, object]]:
    root = root.resolve()
    term_pairs = term_pairs or []
    main_path, main_note = detect_main(root, main)
    tex_files, unresolved_sources = active_source_graph(root, main_path)
    findings: list[Finding] = []

    raw_sources = {
        path: path.read_text(encoding="utf-8", errors="replace")
        for path in tex_files
    }
    sources = {path: strip_comments(text) for path, text in raw_sources.items()}
    bib_files, unresolved_bibs = active_bibliographies(root, sources)
    graphics_paths, graphics_extensions = collect_graphics_configuration(root, sources)

    if main_note:
        add(
            findings,
            root,
            check_id="main-file-ambiguity",
            status="not_verified",
            priority="medium",
            confidence="high",
            suggested_severity="P1-P3 depending on whether the selected root is the submitted document",
            path=main_path,
            line=1,
            message=main_note,
            possible_false_positive="自动选择可能恰好与实际构建入口一致。",
            confirmation_action="用实际编译命令或编辑器配置确认主文件；必要时显式传入 --main。",
        )

    for path, line, reference in unresolved_sources:
        add(
            findings,
            root,
            check_id="source-dependency-unresolved",
            status="not_verified",
            priority="high",
            confidence="high",
            suggested_severity="P0-P2 if the dependency is active and required",
            path=path,
            line=line,
            message=f"无法解析活动源码依赖 {reference!r}",
            possible_false_positive="依赖可能由宏、搜索路径、条件分支或外部构建工具解析。",
            confirmation_action="检查实际编译日志和宏展开，确认依赖是否活动且能被加载。",
        )
    for path, line, reference in unresolved_bibs:
        add(
            findings,
            root,
            check_id="bibliography-resource-unresolved",
            status="not_verified",
            priority="high",
            confidence="high",
            suggested_severity="P0-P2 if citations depend on this resource",
            path=path,
            line=line,
            message=f"无法解析活动参考文献资源 {reference!r}",
            possible_false_positive="资源可能通过 TEXINPUTS、宏或构建工具提供。",
            confirmation_action="检查 .log/.blg 和构建配置，确认实际加载的 bibliography。",
        )

    if any(re.search(r"\\if(?:\w+|true|false)\b|\\else\b|\\fi\b", text) for text in sources.values()):
        add(
            findings,
            root,
            check_id="conditional-coverage",
            status="not_verified",
            priority="low",
            confidence="high",
            suggested_severity="P1-P3 only if inactive branches affect submitted content",
            path=main_path,
            line=1,
            message="活动源码包含条件编译；静态扫描未计算完整 TeX 条件状态",
            possible_false_positive="多数条件可能只控制模板版式，不改变正文依赖。",
            confirmation_action="以本次提交的编译开关和 .fls/.log 核对实际加载文件。",
        )

    labels: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    references: list[tuple[str, Path, int]] = []
    citations: list[tuple[str, Path, int]] = []
    object_labels: dict[str, tuple[Path, int, str]] = {}
    chapter_titles: dict[str, list[tuple[Path, int]]] = defaultdict(list)

    label_re = re.compile(r"\\label\s*\{([^{}]+)\}")
    ref_re = re.compile(r"\\(?:ref|eqref|autoref|pageref|cref|Cref)\s*\{([^{}]+)\}")
    cite_re = re.compile(
        r"\\(?:cite|citet|citep|upcite|parencite|textcite|supercite)\w*"
        r"\s*(?:\[[^\]]*\]\s*)*\{([^{}]+)\}"
    )
    caption_re = re.compile(r"\\caption(?:\s*\[[^\]]*\])?\s*(\{)")
    chapter_re = re.compile(r"\\chapter\*?\s*\{([^{}]+)\}")
    graphics_re = re.compile(r"\\includegraphics\*?\s*(?:\[[^\]]*\]\s*)?\{([^{}]+)\}")
    float_re = re.compile(
        r"\\begin\s*\{(figure\*?|table\*?|algorithm\*?)\}(.*?)"
        r"\\end\s*\{\1\}",
        re.DOTALL,
    )

    for path, text in sources.items():
        if not text.strip():
            add(
                findings,
                root,
                check_id="empty-active-source",
                priority="medium",
                confidence="high",
                suggested_severity="P1-P3 depending on whether content is expected",
                path=path,
                line=1,
                message="活动 TeX 文件除注释和空白外没有有效内容",
                possible_false_positive="文件可能是有意保留的空钩子或条件入口。",
                confirmation_action="检查主文件加载目的和当前 PDF 是否缺少预期内容。",
            )

        for match in chapter_re.finditer(text):
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            if title:
                chapter_titles[title].append((path, line_number(text, match.start())))

        for match in graphics_re.finditer(text):
            target = match.group(1).strip()
            line = line_number(text, match.start())
            if not target or any(token in target for token in ("\\", "#")):
                add(
                    findings,
                    root,
                    check_id="graphics-path-unresolved",
                    status="not_verified",
                    priority="medium",
                    confidence="high",
                    suggested_severity="P1-P3 if the rendered object is missing",
                    path=path,
                    line=line,
                    message=f"图片路径包含无法静态展开的宏或参数：{target!r}",
                    possible_false_positive="TeX 编译时可能能够正确展开该路径。",
                    confirmation_action="检查编译日志并在当前 PDF 中确认图片存在且正确。",
                )
                continue
            if Path(target).is_absolute() and check_provenance:
                add(
                    findings,
                    root,
                    check_id="absolute-graphics-path",
                    priority="medium",
                    confidence="high",
                    suggested_severity="P2",
                    path=path,
                    line=line,
                    message=f"图片使用绝对路径 {target!r}",
                    possible_false_positive="若只在固定归档环境构建，绝对路径未必影响当前提交物。",
                    confirmation_action="在干净副本或目标构建环境中重新编译。",
                )
            candidates = graphics_candidates(root, path, target, graphics_paths, graphics_extensions)
            if not any(candidate.is_file() for candidate in candidates):
                add(
                    findings,
                    root,
                    check_id="missing-graphics-file",
                    priority="high",
                    confidence="high",
                    suggested_severity="P0-P2 depending on whether the object is required and visible",
                    path=path,
                    line=line,
                    message=f"未找到 includegraphics 指向的文件 {target!r}",
                    possible_false_positive="文件可能由构建步骤生成，或通过未解析的 TeX 搜索路径提供。",
                    confirmation_action="检查实际编译日志和当前 PDF；确认路径、扩展名及大小写。",
                )

        for token, description in GARBLED_PATTERNS.items():
            start = 0
            while True:
                offset = text.find(token, start)
                if offset < 0:
                    break
                add(
                    findings,
                    root,
                    check_id="garbled-source-text",
                    priority="high",
                    confidence="medium",
                    suggested_severity="P0-P2 after source and PDF confirmation",
                    path=path,
                    line=line_number(text, offset),
                    message=f"活动正文中发现{description}",
                    possible_false_positive="字符可能位于合法示例、代码或不会进入 PDF 的宏参数中。",
                    confirmation_action="核对源码语义并渲染相应 PDF 页面确认是否可见。",
                )
                start = offset + len(token)

        for marker, pattern in DRAFT_PATTERNS.items():
            for match in pattern.finditer(text):
                add(
                    findings,
                    root,
                    check_id="draft-marker",
                    priority="high",
                    confidence="medium",
                    suggested_severity="P0-P2 if visible or replacing required content",
                    path=path,
                    line=line_number(text, match.start()),
                    message=f"活动源码中发现草稿标记 {marker}",
                    possible_false_positive="可能是论文讨论的字面术语、代码示例或不会显示的宏内容。",
                    confirmation_action="查看上下文及当前 PDF，确认是否为可见占位内容。",
                )

        for match in re.finditer(r"\?\?", text):
            add(
                findings,
                root,
                check_id="double-question-mark",
                priority="high",
                confidence="medium",
                suggested_severity="P0-P2 after build/PDF confirmation",
                path=path,
                line=line_number(text, match.start()),
                message="活动源码中发现连续问号",
                possible_false_positive="可能是合法问句、示例文本或非交叉引用内容。",
                confirmation_action="结合编译日志和 PDF 判断是否为未解析引用或占位。",
            )

        for left, right, name in (("“", "”", "中文双引号"), ("‘", "’", "中文单引号"), ("《", "》", "书名号")):
            if text.count(left) != text.count(right):
                line = unmatched_punctuation_line(text, left, right) or 1
                add(
                    findings,
                    root,
                    check_id="unbalanced-punctuation",
                    priority="medium",
                    confidence="medium",
                    suggested_severity="P2",
                    path=path,
                    line=line,
                    message=f"{name}数量不匹配：左 {text.count(left)}，右 {text.count(right)}",
                    possible_false_positive="跨文件配对、代码、公式或自定义宏可能造成计数失真。",
                    confirmation_action="从所示疑似位置开始核对活动正文和渲染文本。",
                )

        for match in label_re.finditer(text):
            labels[match.group(1).strip()].append((path, line_number(text, match.start())))
        for match in ref_re.finditer(text):
            for key in match.group(1).split(","):
                references.append((key.strip(), path, line_number(text, match.start())))
        for match in cite_re.finditer(text):
            for key in match.group(1).split(","):
                citations.append((key.strip(), path, line_number(text, match.start())))

        for match in caption_re.finditer(text):
            if extract_braced(text, match.start(1)) is None:
                add(
                    findings,
                    root,
                    check_id="unclosed-caption",
                    priority="high",
                    confidence="high",
                    suggested_severity="P0-P2 depending on build impact",
                    path=path,
                    line=line_number(text, match.start()),
                    message="caption 花括号可能未闭合",
                    possible_false_positive="复杂宏展开可能超出静态解析能力。",
                    confirmation_action="检查该命令并重新编译，确认无语法错误和目录异常。",
                )

        for old, new in term_pairs:
            start = 0
            while True:
                offset = text.find(old, start)
                if offset < 0:
                    break
                add(
                    findings,
                    root,
                    check_id="retired-term",
                    priority="medium",
                    confidence="high",
                    suggested_severity="P2-P3",
                    path=path,
                    line=line_number(text, offset),
                    message=f"发现候选旧术语 {old!r}，目标术语为 {new!r}",
                    possible_false_positive="可能位于历史回顾、引用标题、专名或需要保留的对比语境。",
                    confirmation_action="逐处核对语义，不做无上下文全局替换。",
                )
                start = offset + len(old)

        for match in float_re.finditer(text):
            environment, body = match.group(1), match.group(2)
            line = line_number(text, match.start())
            top_level_body = re.sub(
                r"\\begin\s*\{subfigure\}.*?\\end\s*\{subfigure\}",
                "",
                body,
                flags=re.DOTALL,
            )
            body_labels = list(label_re.finditer(top_level_body))
            if "\\caption" not in body:
                add(
                    findings,
                    root,
                    check_id="missing-caption",
                    priority="medium",
                    confidence="high",
                    suggested_severity="P1-P3 depending on the object's role",
                    path=path,
                    line=line,
                    message=f"{environment} 环境未检测到 caption",
                    possible_false_positive="对象可能是装饰性、由自定义宏提供 caption，或模板允许无题对象。",
                    confirmation_action="确认该对象是否为主要图表及当前 PDF 是否具备必要说明。",
                )
            for label_match in body_labels:
                key = label_match.group(1).strip()
                object_labels[key] = (path, line, environment)

    for key, occurrences in labels.items():
        if len(occurrences) > 1:
            first_path, first_line = occurrences[0]
            locations = ", ".join(f"{display_path(path, root)}:{line}" for path, line in occurrences)
            add(
                findings,
                root,
                check_id="duplicate-label",
                priority="high",
                confidence="high",
                suggested_severity="P0-P2 depending on compiled reference behavior",
                path=first_path,
                line=first_line,
                message=f"活动源码中的 label {key!r} 重复：{locations}",
                possible_false_positive="条件编译可能使其中一个定义在本次构建中不活动。",
                confirmation_action="结合本次编译开关、.log 和 PDF 跳转确认实际影响。",
            )

    for title, occurrences in chapter_titles.items():
        if len(occurrences) > 1:
            first_path, first_line = occurrences[0]
            locations = ", ".join(f"{display_path(path, root)}:{line}" for path, line in occurrences)
            add(
                findings,
                root,
                check_id="duplicate-chapter-title",
                priority="medium",
                confidence="high",
                suggested_severity="P1-P3 depending on whether duplicate chapters render",
                path=first_path,
                line=first_line,
                message=f"活动源码中章标题 {title!r} 重复：{locations}",
                possible_false_positive="重复名称可能有意使用，或条件编译只激活一章。",
                confirmation_action="检查目录和当前 PDF 是否出现结构重复或误加载。",
            )

    label_keys = set(labels)
    for key, path, line in references:
        if key and key not in label_keys:
            add(
                findings,
                root,
                check_id="missing-label-target",
                priority="high",
                confidence="high",
                suggested_severity="P0-P2 depending on build/PDF visibility and importance",
                path=path,
                line=line,
                message=f"活动源码引用的 label {key!r} 未在活动源码图中找到",
                possible_false_positive="label 可能由宏、外部文档或未解析条件分支生成。",
                confirmation_action="检查 .log 中 undefined reference，并在当前 PDF 核对显示和跳转。",
            )

    referenced_keys = {key for key, _, _ in references}
    for key, (path, line, environment) in object_labels.items():
        if key not in referenced_keys:
            add(
                findings,
                root,
                check_id="unreferenced-object",
                priority="low",
                confidence="medium",
                suggested_severity="P1-P3 depending on whether it supports a core claim",
                path=path,
                line=line,
                message=f"{environment} 的 label {key!r} 未被可解析的交叉引用使用",
                possible_false_positive="正文可能手写编号、通过自定义宏引用，或该对象无需正文引用。",
                confirmation_action="判断其是否为主要图表，并检查正文是否实质解释该对象。",
            )

    bib_keys: set[str] = set()
    bib_re = re.compile(r"@(?!comment|string|preamble)\w+\s*\{\s*([^,\s]+)", re.IGNORECASE)
    for path in bib_files:
        bib_text = path.read_text(encoding="utf-8", errors="replace")
        bib_keys.update(match.group(1).strip() for match in bib_re.finditer(bib_text))
    if bib_files:
        for key, path, line in citations:
            if key and key != "*" and key not in bib_keys:
                add(
                    findings,
                    root,
                    check_id="missing-bib-entry",
                    priority="high",
                    confidence="high",
                    suggested_severity="P0-P2 depending on build/PDF visibility",
                    path=path,
                    line=line,
                    message=f"引用键 {key!r} 不存在于活动 bibliography 资源",
                    possible_false_positive="键可能由远程资源、宏或未解析条件分支提供。",
                    confirmation_action="检查 .blg/.log 和最终参考文献，确认引用是否解析。",
                )
    elif citations:
        first_key, first_path, first_line = citations[0]
        add(
            findings,
            root,
            check_id="missing-bibliography",
            priority="high",
            confidence="high",
            suggested_severity="P0-P2 depending on build configuration",
            path=first_path,
            line=first_line,
            message=f"发现 {len(citations)} 处引文（首个键 {first_key!r}），但未识别到活动 bibliography 资源",
            possible_false_positive="参考文献可能由自定义宏、外部文档或构建工具提供。",
            confirmation_action="检查主文件、构建命令、.blg/.log 和最终参考文献。",
        )

    artifacts = project_artifacts(root)
    repository_state = git_repository_state(root) if check_provenance else None
    tracked_artifacts = 0
    if check_provenance:
        tracked_files = git_tracked_files(root)
        for path in artifacts:
            relative = display_path(path, root)
            if relative not in tracked_files:
                continue
            tracked_artifacts += 1
            add(
                findings,
                root,
                check_id="tracked-project-artifact",
                priority="low",
                confidence="high",
                suggested_severity="P2-P3",
                path=path,
                line=1,
                message="构建辅助文件或文件系统伪文件已被 Git 跟踪",
                possible_false_positive="项目可能有意版本化某些生成文件。",
                confirmation_action="核对仓库策略和实际提交包，再决定是否移除。",
            )

    findings.sort(key=lambda item: (PRIORITY_ORDER[item.priority], item.status != "candidate", item.path, item.line, item.check_id))
    all_tex = source_files(root, ".tex")
    all_bib = source_files(root, ".bib")
    summary: dict[str, object] = {
        "root": str(root),
        "main": display_path(main_path, root),
        "active_tex_files": len(tex_files),
        "inactive_tex_files": max(0, len(all_tex) - len(set(tex_files))),
        "active_bib_files": len(bib_files),
        "inactive_bib_files": max(0, len(all_bib) - len(set(bib_files))),
        "active_tex_paths": [display_path(path, root) for path in tex_files],
        "active_bib_paths": [display_path(path, root) for path in bib_files],
        "labels": len(labels),
        "references": len(references),
        "citations": len(citations),
        "floating_objects_with_labels": len(object_labels),
        "chapter_titles": len(chapter_titles),
        "unresolved_source_dependencies": len(unresolved_sources),
        "unresolved_bibliography_resources": len(unresolved_bibs),
        "project_artifacts_observed": len(artifacts),
        "tracked_project_artifacts": tracked_artifacts if check_provenance else None,
        "git": repository_state,
        "candidates_by_priority": dict(Counter(item.priority for item in findings if item.status == "candidate")),
        "not_verified": sum(item.status == "not_verified" for item in findings),
        "coverage": {
            "active_source_graph": "automatic-static",
            "complex_conditionals_and_macros": "not-fully-verified",
            "compile_log": "not-checked",
            "rendered_pdf": "not-checked",
            "git_and_artifacts": "checked" if check_provenance else "not-requested",
        },
        "notice": "输出仅为候选项和覆盖缺口；核对活动构建、PDF 或原始证据后才能赋予最终 P0-P3。",
    }
    return findings, summary


def exit_code(findings: list[Finding], fail_on_priority: str) -> int:
    if fail_on_priority == "never":
        return 0
    threshold = PRIORITY_ORDER[fail_on_priority]
    return 1 if any(item.status == "candidate" and PRIORITY_ORDER[item.priority] <= threshold for item in findings) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="LaTeX 论文项目根目录")
    parser.add_argument("--main", type=Path, help="相对于项目根目录的主 TeX 文件；建议显式提供")
    parser.add_argument("--term", action="append", default=[], metavar="OLD=NEW", help="检查候选旧术语，可重复使用")
    parser.add_argument("--terms-file", type=Path, help="JSON 术语映射文件")
    parser.add_argument("--check-provenance", action="store_true", help="启用 Git 和被跟踪辅助文件检查")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--fail-on-priority", choices=("high", "medium", "low", "never"), default="never")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"目录不存在：{root}")
    try:
        terms_path = args.terms_file.expanduser().resolve() if args.terms_file else None
        terms = parse_term_values(args.term) + load_terms_file(terms_path)
        findings, summary = scan_project(root, terms, args.main, args.check_provenance)
    except (ValueError, json.JSONDecodeError, OSError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps({"summary": summary, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False))
        for item in findings:
            print(
                f"[{item.status}/{item.priority}/{item.confidence}] "
                f"{item.check_id} {item.path}:{item.line} - {item.message}; "
                f"确认后范围：{item.suggested_severity}"
            )
    return exit_code(findings, args.fail_on_priority)


if __name__ == "__main__":
    sys.exit(main())

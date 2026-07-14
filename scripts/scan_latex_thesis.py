#!/usr/bin/env python3
"""Scan a Chinese engineering dissertation LaTeX project for mechanical risks.

The findings are review leads, not final academic judgments. This script only
uses the Python standard library.
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
    "DRAFT": re.compile(r"(?im)^\s*(?:%\s*)?DRAFT(?:\s*[:：].*)?\s*$"),
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


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    line: int
    message: str


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


def source_files(root: Path, suffix: str) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob(f"*{suffix}"):
        relative_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in relative_parts[:-1]):
            continue
        if path.name.startswith("._"):
            continue
        found.append(path)
    return sorted(found)


def project_artifacts(root: Path) -> list[Path]:
    """Return common generated or filesystem artifacts outside skipped directories."""
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
            found.append(path)
    return sorted(found)


def git_tracked_files(root: Path) -> set[str]:
    """Return Git-tracked paths when root is a repository; otherwise return empty."""
    state = git_repository_state(root)
    if state is None:
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
    return {item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item}


def git_repository_state(root: Path) -> dict[str, object] | None:
    """Return provenance only when root itself is the Git worktree root."""
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


def extract_braced(text: str, open_brace: int) -> tuple[str, int] | None:
    """Extract balanced braced content starting at an opening brace."""
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


def display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def add(
    findings: list[Finding],
    root: Path,
    severity: str,
    code: str,
    path: Path,
    line: int,
    message: str,
) -> None:
    findings.append(Finding(severity, code, display_path(path, root), line, message))


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


def caption_plain_end(caption: str) -> str:
    plain = re.sub(r"\\(?:label|footnote)\s*\{[^{}]*\}", "", caption)
    plain = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", "", plain)
    plain = re.sub(r"[{}\s~]+$", "", plain)
    return plain[-1] if plain else ""


def graphics_candidates(root: Path, tex_path: Path, raw_target: str) -> list[Path]:
    target = Path(raw_target.strip())
    bases = [target] if target.is_absolute() else [tex_path.parent / target, root / target]
    extensions = ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")
    candidates: list[Path] = []
    for base in bases:
        if base.suffix:
            candidates.append(base)
        else:
            candidates.extend(Path(f"{base}{extension}") for extension in extensions)
    return candidates


def scan_project(root: Path, term_pairs: list[tuple[str, str]] | None = None) -> tuple[list[Finding], dict[str, object]]:
    root = root.resolve()
    term_pairs = term_pairs or []
    tex_files = source_files(root, ".tex")
    bib_files = source_files(root, ".bib")
    findings: list[Finding] = []

    artifacts = project_artifacts(root)
    tracked_files = git_tracked_files(root)
    repository_state = git_repository_state(root)
    tracked_artifacts = 0
    for path in artifacts:
        relative = display_path(path, root)
        tracked = relative in tracked_files
        tracked_artifacts += int(tracked)
        add(
            findings,
            root,
            "P2" if tracked else "P3",
            "tracked-project-artifact" if tracked else "project-artifact",
            path,
            1,
            (
                "构建辅助文件或文件系统伪文件已被 Git 跟踪；确认是否应从版本库和提交包中移除"
                if tracked
                else "发现构建辅助文件或文件系统伪文件；确认其未混入提交包且不参与正文扫描"
            ),
        )

    raw_sources: dict[Path, str] = {}
    sources: dict[Path, str] = {}
    for path in tex_files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        raw_sources[path] = raw
        sources[path] = strip_comments(raw)

    labels: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    references: list[tuple[str, Path, int]] = []
    citations: list[tuple[str, Path, int]] = []
    object_labels: dict[str, tuple[Path, int, str]] = {}
    chapter_titles: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    caption_endings = Counter()
    paragraph_endings = Counter()

    label_re = re.compile(r"\\label\s*\{([^{}]+)\}")
    ref_re = re.compile(r"\\(?:ref|eqref|autoref|pageref|cref|Cref)\s*\{([^{}]+)\}")
    cite_re = re.compile(
        r"\\(?:cite|citet|citep|upcite|parencite|textcite|supercite)\w*"
        r"\s*(?:\[[^\]]*\]\s*)*\{([^{}]+)\}"
    )
    caption_re = re.compile(r"\\caption(?:\s*\[[^\]]*\])?\s*(\{)")
    paragraph_re = re.compile(r"\\paragraph\*?\s*\{([^{}]+)\}")
    chapter_re = re.compile(r"\\chapter\*?\s*\{([^{}]+)\}")
    graphics_re = re.compile(r"\\includegraphics\*?\s*(?:\[[^\]]*\]\s*)?\{([^{}]+)\}")
    float_re = re.compile(
        r"\\begin\s*\{(figure\*?|table\*?|algorithm\*?)\}(.*?)"
        r"\\end\s*\{\1\}",
        re.DOTALL,
    )

    for path, text in sources.items():
        raw = raw_sources[path]

        if not text.strip():
            add(findings, root, "P1", "empty-source", path, 1, "TeX 文件除注释和空白外没有有效内容，确认是否仍被主文件加载")

        for match in chapter_re.finditer(text):
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            if title:
                chapter_titles[title].append((path, line_number(text, match.start())))

        for match in graphics_re.finditer(text):
            target = match.group(1).strip()
            if not target or any(token in target for token in ("\\", "#")):
                continue
            line = line_number(text, match.start())
            if Path(target).is_absolute():
                add(findings, root, "P1", "absolute-graphics-path", path, line, f"图片使用绝对路径 {target!r}，在干净副本或他人环境中不可移植")
            if not any(candidate.is_file() for candidate in graphics_candidates(root, path, target)):
                add(findings, root, "P1", "missing-graphics-file", path, line, f"未找到 includegraphics 指向的文件 {target!r}；检查路径、扩展名和文件名大小写")

        for token, description in GARBLED_PATTERNS.items():
            start = 0
            while True:
                offset = raw.find(token, start)
                if offset < 0:
                    break
                add(findings, root, "P0", "garbled-text", path, line_number(raw, offset), f"发现{description}")
                start = offset + len(token)

        for marker, pattern in DRAFT_PATTERNS.items():
            for match in pattern.finditer(text):
                add(findings, root, "P1", "draft-marker", path, line_number(text, match.start()), f"发现草稿标记 {marker}")

        for match in re.finditer(r"\?\?", text):
            add(findings, root, "P1", "double-question-mark", path, line_number(text, match.start()), "发现连续问号，检查未解析引用或占位文本")

        quote_pairs = (("“", "”", "中文双引号"), ("‘", "’", "中文单引号"), ("《", "》", "书名号"))
        for left, right, name in quote_pairs:
            if text.count(left) != text.count(right):
                add(findings, root, "P1", "unbalanced-punctuation", path, 1, f"{name}数量不匹配：左 {text.count(left)}，右 {text.count(right)}")
        for match in re.finditer(r"(?:^|[\s（(：:；;，,。！？!?])”", text, re.MULTILINE):
            add(findings, root, "P2", "suspicious-left-quote", path, line_number(text, match.start()), "疑似用右双引号作为左引号")

        for match in label_re.finditer(text):
            key = match.group(1).strip()
            labels[key].append((path, line_number(text, match.start())))
        for match in ref_re.finditer(text):
            for key in match.group(1).split(","):
                references.append((key.strip(), path, line_number(text, match.start())))
        for match in cite_re.finditer(text):
            for key in match.group(1).split(","):
                citations.append((key.strip(), path, line_number(text, match.start())))

        for match in caption_re.finditer(text):
            extracted = extract_braced(text, match.start(1))
            if not extracted:
                add(findings, root, "P1", "unclosed-caption", path, line_number(text, match.start()), "caption 花括号可能未闭合")
                continue
            caption, _ = extracted
            line = line_number(text, match.start())
            if re.search(r"\\(?:textbf|bfseries|textsc|itshape|emph)\b", caption):
                add(findings, root, "P2", "caption-formatting", path, line, "caption 中包含粗体、小型大写或强调格式命令，检查是否会泄漏到图表目录")
            ending = caption_plain_end(caption)
            caption_endings["with" if ending in "。．.!！；;：:" else "without"] += 1

        for match in paragraph_re.finditer(text):
            title = match.group(1).strip()
            paragraph_endings["with" if title and title[-1] in "。．.!！；;：:" else "without"] += 1

        for old, new in term_pairs:
            start = 0
            while True:
                offset = text.find(old, start)
                if offset < 0:
                    break
                add(findings, root, "P2", "retired-term", path, line_number(text, offset), f"发现旧术语 {old!r}，人工判断是否应统一为 {new!r}")
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
                add(findings, root, "P1", "missing-caption", path, line, f"{environment} 环境缺少 caption")
            if not body_labels:
                add(findings, root, "P2", "missing-label", path, line, f"{environment} 环境缺少 label，无法稳定交叉引用")
            for label_match in body_labels:
                key = label_match.group(1).strip()
                object_labels[key] = (path, line, environment)

    for key, occurrences in labels.items():
        if len(occurrences) > 1:
            first_path, first_line = occurrences[0]
            locations = ", ".join(f"{display_path(path, root)}:{line}" for path, line in occurrences)
            add(findings, root, "P0", "duplicate-label", first_path, first_line, f"label {key!r} 重复：{locations}")

    for title, occurrences in chapter_titles.items():
        if len(occurrences) > 1:
            first_path, first_line = occurrences[0]
            locations = ", ".join(f"{display_path(path, root)}:{line}" for path, line in occurrences)
            add(findings, root, "P1", "duplicate-chapter-title", first_path, first_line, f"章标题 {title!r} 被重复声明：{locations}")

    label_keys = set(labels)
    for key, path, line in references:
        if key and key not in label_keys:
            add(findings, root, "P0", "missing-label-target", path, line, f"引用的 label {key!r} 不存在")

    referenced_keys = {key for key, _, _ in references}
    for key, (path, line, environment) in object_labels.items():
        if key not in referenced_keys:
            appendix_like = "appendix" in path.stem.lower() or "附录" in path.name
            add(
                findings,
                root,
                "P2" if appendix_like else "P1",
                "unreferenced-object",
                path,
                line,
                f"{environment} 的 label {key!r} 未被正文交叉引用",
            )

    bib_keys: set[str] = set()
    bib_re = re.compile(r"@(?!comment|string|preamble)\w+\s*\{\s*([^,\s]+)", re.IGNORECASE)
    for path in bib_files:
        bib_text = path.read_text(encoding="utf-8", errors="replace")
        bib_keys.update(match.group(1).strip() for match in bib_re.finditer(bib_text))
    if bib_files:
        for key, path, line in citations:
            if key and key != "*" and key not in bib_keys:
                add(findings, root, "P0", "missing-bib-entry", path, line, f"引用键 {key!r} 不存在于已扫描 bib 文件")
    elif citations:
        first_key, first_path, first_line = citations[0]
        add(findings, root, "P0", "missing-bibliography", first_path, first_line, f"发现 {len(citations)} 处引文（首个键为 {first_key!r}），但项目中未扫描到 bib 文件")

    if caption_endings["with"] and caption_endings["without"]:
        add(findings, root, "P2", "mixed-caption-punctuation", root, 1, f"caption 末尾标点风格混用：有标点 {caption_endings['with']}，无标点 {caption_endings['without']}")
    if paragraph_endings["with"] and paragraph_endings["without"]:
        add(findings, root, "P2", "mixed-paragraph-punctuation", root, 1, f"paragraph 标题末尾标点风格混用：有标点 {paragraph_endings['with']}，无标点 {paragraph_endings['without']}")

    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    findings.sort(key=lambda item: (severity_order[item.severity], item.path, item.line, item.code))
    summary: dict[str, object] = {
        "root": str(root),
        "git": repository_state,
        "tex_files": len(tex_files),
        "bib_files": len(bib_files),
        "labels": len(labels),
        "references": len(references),
        "citations": len(citations),
        "floating_objects": len(object_labels),
        "chapter_titles": len(chapter_titles),
        "project_artifacts": len(artifacts),
        "tracked_project_artifacts": tracked_artifacts,
        "findings": dict(Counter(item.severity for item in findings)),
        "notice": "自动扫描仅提供机械风险线索，需结合源码上下文和最终 PDF 人工判断。",
    }
    return findings, summary


def exit_code(findings: list[Finding], fail_on: str) -> int:
    if fail_on == "never":
        return 0
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    threshold = order[fail_on]
    return 1 if any(order[item.severity] <= threshold for item in findings) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="LaTeX 论文项目根目录")
    parser.add_argument("--term", action="append", default=[], metavar="OLD=NEW", help="检查旧术语，可重复使用")
    parser.add_argument("--terms-file", type=Path, help="JSON 术语映射文件")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--fail-on", choices=("P0", "P1", "P2", "P3", "never"), default="never")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"目录不存在：{root}")
    try:
        terms = parse_term_values(args.term) + load_terms_file(args.terms_file.expanduser().resolve() if args.terms_file else None)
    except (ValueError, json.JSONDecodeError, OSError) as error:
        parser.error(str(error))

    findings, summary = scan_project(root, terms)
    if args.json:
        print(json.dumps({"summary": summary, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False))
        for item in findings:
            print(f"[{item.severity}] {item.code} {item.path}:{item.line} - {item.message}")
    return exit_code(findings, args.fail_on)


if __name__ == "__main__":
    sys.exit(main())

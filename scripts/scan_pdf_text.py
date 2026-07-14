#!/usr/bin/env python3
"""Inspect PDF metadata and extracted text for review candidates.

Requires ``pdfinfo`` and ``pdftotext``. The scanner does not confirm visual
layout defects or assign final P0-P3 severities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path


DRAFT_RE = re.compile(r"\b(?:TODO|FIXME|TBD|DRAFT|XXX)\b|待补(?:充|写|引用|实验|数据)?|待定", re.IGNORECASE)
GARBLED = ("�", "锟斤拷", "Ã", "â€")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class Finding:
    check_id: str
    status: str
    priority: str
    confidence: str
    requires_confirmation: bool
    suggested_severity: str
    page: int | None
    message: str
    possible_false_positive: str
    confirmation_action: str

    @property
    def code(self) -> str:
        """Compatibility alias for older callers."""
        return self.check_id


def candidate(
    check_id: str,
    *,
    page: int | None,
    message: str,
    priority: str,
    confidence: str,
    suggested_severity: str,
    possible_false_positive: str,
    confirmation_action: str,
    status: str = "candidate",
) -> Finding:
    return Finding(
        check_id=check_id,
        status=status,
        priority=priority,
        confidence=confidence,
        requires_confirmation=True,
        suggested_severity=suggested_severity,
        page=page,
        message=message,
        possible_false_positive=possible_false_positive,
        confirmation_action=confirmation_action,
    )


def command_output(args: list[str]) -> str:
    return subprocess.check_output(args, text=True, errors="replace", stderr=subprocess.STDOUT)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extractable_text_estimate(text: str) -> tuple[int, int, int]:
    """Estimate extractable text volume as CJK characters plus Latin/digit tokens."""
    cjk_re = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
    latin_re = re.compile(r"[A-Za-z0-9]+(?:[-_/.][A-Za-z0-9]+)*")
    cjk_count = len(cjk_re.findall(text))
    latin_count = len(latin_re.findall(cjk_re.sub(" ", text)))
    return cjk_count + latin_count, cjk_count, latin_count


def word_like_count(text: str) -> tuple[int, int, int]:
    """Deprecated compatibility alias; use extractable_text_estimate."""
    return extractable_text_estimate(text)


def parse_pdfinfo(info_text: str) -> dict[str, object]:
    def value(name: str) -> str | None:
        match = re.search(rf"^{re.escape(name)}:\s*(.+)$", info_text, re.MULTILINE | re.IGNORECASE)
        return match.group(1).strip() if match else None

    pages_text = value("Pages")
    return {
        "pages": int(pages_text) if pages_text and pages_text.isdigit() else None,
        "page_size": value("Page size") or "unknown",
        "encrypted": value("Encrypted") or "unknown",
        "file_size": value("File size") or "unknown",
        "pdf_version": value("PDF version") or "unknown",
    }


def numeric_page_size(page_size: str) -> tuple[float, float] | None:
    match = re.search(r"([0-9.]+)\s*x\s*([0-9.]+)\s*pts", page_size, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def is_a4(page_size: str, tolerance_points: float = 3.0) -> bool:
    if "A4" in page_size.upper():
        return True
    dimensions = numeric_page_size(page_size)
    if dimensions is None:
        return False
    width, height = dimensions
    return (
        abs(width - 595.28) <= tolerance_points and abs(height - 841.89) <= tolerance_points
    ) or (
        abs(height - 595.28) <= tolerance_points and abs(width - 841.89) <= tolerance_points
    )


def is_letter(page_size: str, tolerance_points: float = 3.0) -> bool:
    if "LETTER" in page_size.upper():
        return True
    dimensions = numeric_page_size(page_size)
    if dimensions is None:
        return False
    width, height = dimensions
    return (
        abs(width - 612.0) <= tolerance_points and abs(height - 792.0) <= tolerance_points
    ) or (
        abs(height - 612.0) <= tolerance_points and abs(width - 792.0) <= tolerance_points
    )


def matches_expected_page_size(page_size: str, expected: str, tolerance_points: float = 3.0) -> bool:
    normalized = expected.strip().upper()
    if normalized == "A4":
        return is_a4(page_size, tolerance_points)
    if normalized in {"LETTER", "US-LETTER", "US LETTER"}:
        return is_letter(page_size, tolerance_points)
    expected_dimensions = numeric_page_size(expected)
    actual_dimensions = numeric_page_size(page_size)
    if expected_dimensions is None or actual_dimensions is None:
        raise ValueError("--expected-page-size 应为 A4、Letter 或如 '595 x 842 pts' 的尺寸")
    expected_width, expected_height = expected_dimensions
    width, height = actual_dimensions
    return (
        abs(width - expected_width) <= tolerance_points
        and abs(height - expected_height) <= tolerance_points
    ) or (
        abs(height - expected_width) <= tolerance_points
        and abs(width - expected_height) <= tolerance_points
    )


def parse_per_page_sizes(info_text: str) -> dict[int, str]:
    sizes: dict[int, str] = {}
    pattern = re.compile(r"^Page\s+(\d+)\s+size:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
    for match in pattern.finditer(info_text):
        sizes[int(match.group(1))] = match.group(2).strip()
    return sizes


def split_pages(text: str) -> list[str]:
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def scan_pdf(
    pdf: Path,
    low_text_threshold: int = 30,
    expected_page_size: str | None = None,
    include_sha256: bool = False,
) -> tuple[list[Finding], dict[str, object]]:
    missing = [name for name in ("pdfinfo", "pdftotext") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"缺少可选系统命令：{', '.join(missing)}")

    info_text = command_output(["pdfinfo", str(pdf)])
    visible_text = command_output(["pdftotext", "-layout", str(pdf), "-"])
    metadata = parse_pdfinfo(info_text)
    pages = split_pages(visible_text)
    findings: list[Finding] = []
    diagnostics: list[str] = []

    declared_pages = metadata["pages"]
    detailed_info = ""
    if isinstance(declared_pages, int) and declared_pages > 0:
        try:
            detailed_info = command_output(["pdfinfo", "-f", "1", "-l", str(declared_pages), str(pdf)])
        except subprocess.CalledProcessError:
            diagnostics.append("无法读取逐页页面尺寸，仅报告 pdfinfo 总体尺寸")
    per_page_sizes = parse_per_page_sizes(detailed_info)
    observed_sizes = per_page_sizes or ({1: str(metadata["page_size"])} if metadata["page_size"] != "unknown" else {})

    mismatched_pages: list[int] = []
    if expected_page_size is not None:
        for page_number, size in observed_sizes.items():
            if not matches_expected_page_size(size, expected_page_size):
                mismatched_pages.append(page_number)
        if mismatched_pages:
            findings.append(
                candidate(
                    "unexpected-page-size",
                    page=mismatched_pages[0] if len(mismatched_pages) == 1 else None,
                    priority="high",
                    confidence="high",
                    suggested_severity="P0-P2 depending on institutional requirements and affected pages",
                    message=f"检测到不符合期望尺寸 {expected_page_size!r} 的页面：{mismatched_pages}",
                    possible_false_positive="学校可能允许封面、横向表格或附件使用不同尺寸；逐页元数据也可能不完整。",
                    confirmation_action="核对学校规格并渲染所列页面确认实际尺寸和内容。",
                )
            )
    elif observed_sizes:
        diagnostics.append("未提供期望页面尺寸；仅记录观测尺寸，不判断是否合规")

    if isinstance(declared_pages, int) and abs(declared_pages - len(pages)) > 1:
        diagnostics.append(f"pdfinfo 为 {declared_pages} 页，pdftotext 提取为 {len(pages)} 页；这是工具诊断，不等同于 PDF 缺页")

    low_text_pages: list[int] = []
    for page_number, page in enumerate(pages, start=1):
        compact = re.sub(r"\s+", "", page)
        if len(compact) < low_text_threshold:
            low_text_pages.append(page_number)
        for token in GARBLED:
            if token in page:
                findings.append(
                    candidate(
                        "text-layer-garbled",
                        page=page_number,
                        priority="high",
                        confidence="medium",
                        suggested_severity="P0-P2 after visual and searchability confirmation",
                        message=f"PDF 文本层中发现疑似乱码 {token!r}",
                        possible_false_positive="字体 ToUnicode 映射可能只影响文本提取，页面视觉内容仍正常。",
                        confirmation_action="渲染该页视觉检查，并测试复制、搜索和学校对文本层的要求。",
                    )
                )
        if "??" in page:
            findings.append(
                candidate(
                    "double-question-mark",
                    page=page_number,
                    priority="high",
                    confidence="medium",
                    suggested_severity="P0-P2 depending on whether it is an unresolved reference",
                    message="PDF 提取文本中发现连续问号",
                    possible_false_positive="可能是合法问句、问卷文本或字体提取结果。",
                    confirmation_action="视觉检查该页并结合编译日志确认是否存在未解析引用。",
                )
            )
        if re.search(r"(?:Citation|Reference)\s+[^\n]{0,30}\?", page, re.IGNORECASE):
            findings.append(
                candidate(
                    "unresolved-reference-text",
                    page=page_number,
                    priority="high",
                    confidence="medium",
                    suggested_severity="P0-P2 after build/PDF confirmation",
                    message="PDF 文本层疑似存在未解析 Citation/Reference",
                    possible_false_positive="提取文本可能误拼接相邻字符，或正文正在讨论该字面内容。",
                    confirmation_action="视觉检查该页并核对当前完整编译日志。",
                )
            )
        draft_match = DRAFT_RE.search(page)
        if draft_match:
            findings.append(
                candidate(
                    "visible-draft-marker",
                    page=page_number,
                    priority="high",
                    confidence="medium",
                    suggested_severity="P0-P2 depending on context and missing content",
                    message=f"PDF 提取文本中发现疑似草稿标记 {draft_match.group(0)!r}",
                    possible_false_positive="可能是论文讨论对象、代码、表格字段或合法字面文本。",
                    confirmation_action="视觉检查上下文并判断是否为未完成内容。",
                )
            )

    estimate, cjk, latin = extractable_text_estimate(visible_text)
    findings.sort(key=lambda item: (PRIORITY_ORDER[item.priority], item.page or 0, item.check_id))
    summary: dict[str, object] = {
        "pdf": str(pdf.resolve()),
        "sha256": file_sha256(pdf) if include_sha256 else None,
        "pages_pdfinfo": declared_pages,
        "pages_extracted": len(pages),
        "observed_page_size": metadata["page_size"],
        "observed_distinct_page_sizes": sorted(set(observed_sizes.values())),
        "per_page_size_coverage": "all-reported-pages" if per_page_sizes else "overall-only",
        "expected_page_size": expected_page_size,
        "page_size_matches_expected": None if expected_page_size is None else not mismatched_pages,
        "encrypted": metadata["encrypted"],
        "file_size": metadata["file_size"],
        "pdf_version": metadata["pdf_version"],
        "extractable_text_estimate": estimate,
        "cjk_characters": cjk,
        "latin_or_digit_tokens": latin,
        "count_method": "PDF 可提取文本中的中文字符数 + 拉丁/数字词元数；不得作为学校、Word、texcount 或查重系统官方字数",
        "visual_navigation": {
            "low_text_threshold": low_text_threshold,
            "low_text_pages": low_text_pages,
            "note": "低文本页仅用于视觉抽查导航，不构成论文质量问题。",
        },
        "diagnostics": diagnostics,
        "candidates_by_priority": dict(Counter(item.priority for item in findings if item.status == "candidate")),
        "coverage": {
            "metadata": "automatic",
            "text_layer": "automatic-candidates-only",
            "visual_layout": "not-checked",
            "compile_log": "not-checked",
            "institutional_requirements": "provided-page-size-only" if expected_page_size else "not-provided",
            "external_sources": "not-checked",
        },
        "notice": "文本和元数据扫描仅提供候选与导航；渲染确认后才能赋予最终 P0-P3。",
    }
    return findings, summary


def exit_code(findings: list[Finding], fail_on_priority: str) -> int:
    if fail_on_priority == "never":
        return 0
    threshold = PRIORITY_ORDER[fail_on_priority]
    return 1 if any(item.status == "candidate" and PRIORITY_ORDER[item.priority] <= threshold for item in findings) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="论文 PDF")
    parser.add_argument("--expected-page-size", help="学校要求的页面尺寸，例如 A4 或 Letter；未提供则不判断")
    parser.add_argument("--low-text-threshold", type=int, default=30, help="低文本页导航的非空白字符阈值")
    parser.add_argument("--sha256", action="store_true", help="按需计算 PDF SHA-256")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--fail-on-priority", choices=("high", "medium", "low", "never"), default="never")
    args = parser.parse_args()

    pdf = args.pdf.expanduser().resolve()
    if not pdf.is_file():
        parser.error(f"文件不存在：{pdf}")
    if args.low_text_threshold < 0:
        parser.error("--low-text-threshold 不能为负数")
    try:
        findings, summary = scan_pdf(
            pdf,
            low_text_threshold=args.low_text_threshold,
            expected_page_size=args.expected_page_size,
            include_sha256=args.sha256,
        )
    except (RuntimeError, ValueError, subprocess.CalledProcessError, OSError) as error:
        print(f"scan_pdf_text: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"summary": summary, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False))
        for item in findings:
            location = f"第 {item.page} 页" if item.page else "整篇"
            print(
                f"[{item.status}/{item.priority}/{item.confidence}] "
                f"{item.check_id} {location} - {item.message}; "
                f"确认后范围：{item.suggested_severity}"
            )
    return exit_code(findings, args.fail_on_priority)


if __name__ == "__main__":
    sys.exit(main())

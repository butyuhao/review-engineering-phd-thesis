#!/usr/bin/env python3
"""Scan visible text and metadata in a final dissertation PDF.

Requires the optional system commands ``pdfinfo`` and ``pdftotext``. Findings
are mechanical review leads and must be visually confirmed.
"""

from __future__ import annotations

import argparse
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


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    page: int | None
    message: str


def command_output(args: list[str]) -> str:
    return subprocess.check_output(args, text=True, errors="replace", stderr=subprocess.STDOUT)


def word_like_count(text: str) -> tuple[int, int, int]:
    """Approximate Word-like count: CJK characters plus Latin/digit tokens."""
    cjk_re = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
    latin_re = re.compile(r"[A-Za-z0-9]+(?:[-_/.][A-Za-z0-9]+)*")
    cjk_count = len(cjk_re.findall(text))
    latin_count = len(latin_re.findall(cjk_re.sub(" ", text)))
    return cjk_count + latin_count, cjk_count, latin_count


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


def is_a4(page_size: str, tolerance_points: float = 3.0) -> bool:
    if "A4" in page_size.upper():
        return True
    match = re.search(r"([0-9.]+)\s*x\s*([0-9.]+)\s*pts", page_size, re.IGNORECASE)
    if not match:
        return False
    width, height = float(match.group(1)), float(match.group(2))
    portrait = abs(width - 595.28) <= tolerance_points and abs(height - 841.89) <= tolerance_points
    landscape = abs(height - 595.28) <= tolerance_points and abs(width - 841.89) <= tolerance_points
    return portrait or landscape


def split_pages(text: str) -> list[str]:
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def scan_pdf(pdf: Path, low_text_threshold: int = 30) -> tuple[list[Finding], dict[str, object]]:
    missing = [name for name in ("pdfinfo", "pdftotext") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"缺少可选系统命令：{', '.join(missing)}")

    info_text = command_output(["pdfinfo", str(pdf)])
    visible_text = command_output(["pdftotext", "-layout", str(pdf), "-"])
    metadata = parse_pdfinfo(info_text)
    pages = split_pages(visible_text)
    findings: list[Finding] = []

    page_size = str(metadata["page_size"])
    if not is_a4(page_size):
        findings.append(Finding("P1", "non-a4-page-size", None, f"页面尺寸为 {page_size}，请核对学校要求和混合页面尺寸"))

    declared_pages = metadata["pages"]
    if isinstance(declared_pages, int) and abs(declared_pages - len(pages)) > 1:
        findings.append(Finding("P1", "page-extraction-mismatch", None, f"pdfinfo 为 {declared_pages} 页，文本提取为 {len(pages)} 页"))

    low_text_pages: list[int] = []
    for page_number, page in enumerate(pages, start=1):
        compact = re.sub(r"\s+", "", page)
        if len(compact) < low_text_threshold:
            low_text_pages.append(page_number)
        for token in GARBLED:
            if token in page:
                findings.append(Finding("P0", "garbled-text", page_number, f"文本提取中发现疑似乱码 {token!r}，需视觉检查"))
        if "??" in page:
            findings.append(Finding("P1", "double-question-mark", page_number, "发现连续问号，检查未解析交叉引用或占位文本"))
        if re.search(r"(?:Citation|Reference)\s+[^\n]{0,30}\?", page, re.IGNORECASE):
            findings.append(Finding("P0", "unresolved-reference", page_number, "疑似存在未解析 Citation/Reference"))
        draft_match = DRAFT_RE.search(page)
        if draft_match:
            findings.append(Finding("P1", "draft-marker", page_number, f"发现可见草稿标记 {draft_match.group(0)!r}"))

    if low_text_pages:
        findings.append(Finding("P2", "low-text-pages", None, f"非空白字符少于 {low_text_threshold} 的页面：{low_text_pages}；封面、章间空白或整页图片可能合法，需视觉确认"))

    total, cjk, latin = word_like_count(visible_text)
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    findings.sort(key=lambda item: (order[item.severity], item.page or 0, item.code))
    summary: dict[str, object] = {
        "pdf": str(pdf.resolve()),
        "pages_pdfinfo": declared_pages,
        "pages_extracted": len(pages),
        "page_size": page_size,
        "is_a4": is_a4(page_size),
        "encrypted": metadata["encrypted"],
        "file_size": metadata["file_size"],
        "pdf_version": metadata["pdf_version"],
        "word_like_total": total,
        "cjk_characters": cjk,
        "latin_or_digit_tokens": latin,
        "count_method": "PDF 可见文本中的中文字符数 + 拉丁/数字词元数；不是学校或 Word 官方口径",
        "findings": dict(Counter(item.severity for item in findings)),
        "notice": "自动扫描仅提供机械风险线索，低文本页和乱码告警需结合 PDF 视觉检查。",
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
    parser.add_argument("pdf", type=Path, help="最终论文 PDF")
    parser.add_argument("--low-text-threshold", type=int, default=30, help="低文本页的非空白字符阈值")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--fail-on", choices=("P0", "P1", "P2", "P3", "never"), default="never")
    args = parser.parse_args()

    pdf = args.pdf.expanduser().resolve()
    if not pdf.is_file():
        parser.error(f"文件不存在：{pdf}")
    if args.low_text_threshold < 0:
        parser.error("--low-text-threshold 不能为负数")
    try:
        findings, summary = scan_pdf(pdf, args.low_text_threshold)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"scan_pdf_text: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"summary": summary, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False))
        for item in findings:
            location = f"第 {item.page} 页" if item.page else "整篇"
            print(f"[{item.severity}] {item.code} {location} - {item.message}")
    return exit_code(findings, args.fail_on)


if __name__ == "__main__":
    sys.exit(main())

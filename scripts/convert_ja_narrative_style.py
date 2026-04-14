#!/usr/bin/env python3
"""Convert Japanese narrative text from markdown style to Japanese EHR style.

Input markdown style:
    **入院時記録**
    **主訴：** 発熱
    **身体所見：**
    - バイタル：...

Output Japanese EHR style:
    【入院時記録】
    【主訴】発熱
    【身体所見】
    ・バイタル：...
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from pathlib import Path


# Big title on its own line: **XXX**  (no colon)
_RE_BIG_TITLE = re.compile(r'^\*\*([^*\n]+?)\*\*\s*$', re.MULTILINE)
# Section header with content: **XXX：** content  or  **XXX:** content
# Preserve line breaks (use [ \t]* instead of \s*)
_RE_SECTION = re.compile(r'\*\*([^*\n]+?)[：:]\*\*[ \t]*', re.MULTILINE)
# Subheader (remaining bold): **XXX** inline (no colon, not start of line)
_RE_INLINE_BOLD = re.compile(r'\*\*([^*\n]+?)\*\*')
# Dash bullet at start of line: "- item" or "  - item"
_RE_DASH_BULLET = re.compile(r'^(\s*)[-–]\s+', re.MULTILINE)


def _strip_trailing_colon(m: re.Match) -> str:
    """Callback for big title: strip trailing colon from captured title."""
    title = m.group(1).rstrip("：:").strip()
    return f"【{title}】"


def convert_text(text: str) -> str:
    """Convert markdown-style narrative to Japanese EHR style."""
    # 1. Section headers FIRST (longer match): **XXX：** content → 【XXX】content
    text = _RE_SECTION.sub(r'【\1】', text)
    # 2. Big titles on their own line: **XXX** → 【XXX】 (strip trailing colon)
    text = _RE_BIG_TITLE.sub(_strip_trailing_colon, text)
    # 3. Remaining inline bold: **XXX** → ■XXX (rare subheaders)
    text = _RE_INLINE_BOLD.sub(r'■\1', text)
    # 4. Dash bullets → 中黒
    text = _RE_DASH_BULLET.sub(r'\1・', text)
    return text


def convert_document_reference(path: Path) -> tuple[int, int]:
    """Convert DocumentReference.ndjson in place. Returns (converted, total)."""
    lines_out = []
    converted = 0
    total = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            total += 1
            r = json.loads(line)
            att = r.get("content", [{}])[0].get("attachment", {})
            data_b64 = att.get("data", "")
            if not data_b64:
                lines_out.append(json.dumps(r, ensure_ascii=False))
                continue
            original_text = base64.b64decode(data_b64).decode("utf-8")
            new_text = convert_text(original_text)
            if new_text != original_text:
                new_b64 = base64.b64encode(new_text.encode("utf-8")).decode("ascii")
                new_hash = hashlib.sha1(new_text.encode("utf-8")).hexdigest()
                att["data"] = new_b64
                att["size"] = len(new_text.encode("utf-8"))
                att["hash"] = new_hash
                converted += 1
            lines_out.append(json.dumps(r, ensure_ascii=False))

    path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    return converted, total


def convert_narrative_cif_dir(docs_root: Path) -> tuple[int, int]:
    """Convert narrative CIF JSON files in place. Returns (converted, total)."""
    converted = 0
    total = 0
    for enc_dir in docs_root.iterdir():
        if not enc_dir.is_dir():
            continue
        for doc_file in enc_dir.glob("*.json"):
            total += 1
            d = json.loads(doc_file.read_text(encoding="utf-8"))
            original = d.get("text", "")
            new_text = convert_text(original)
            if new_text != original:
                d["text"] = new_text
                doc_file.write_text(
                    json.dumps(d, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                converted += 1
    return converted, total


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: convert_ja_narrative_style.py <path>")
        print("  path: DocumentReference.ndjson OR narrative docs dir")
        sys.exit(1)

    path = Path(sys.argv[1])
    if path.is_file() and path.name.endswith(".ndjson"):
        c, t = convert_document_reference(path)
        print(f"Converted {c}/{t} documents in {path}")
    elif path.is_dir():
        c, t = convert_narrative_cif_dir(path)
        print(f"Converted {c}/{t} documents in {path}")
    else:
        print(f"Error: {path} is not a valid file or directory")
        sys.exit(1)

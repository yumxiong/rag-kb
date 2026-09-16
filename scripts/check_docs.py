"""Check repository Markdown file links and heading anchors without network access."""

import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
PARSER = MarkdownIt("commonmark")


def anchors(text):
    result = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', text))
    seen = {}
    tokens = PARSER.parse(text)
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        inline = tokens[index + 1]
        title = "".join(
            t.content
            for t in inline.children or []
            if t.type in ("text", "code_inline")
        ).lower()
        slug = "".join(
            c for c in title if c in "-_ " or unicodedata.category(c)[0] in "LN"
        ).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def main():
    listed = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode("utf-8")
        .split("\0")
    )
    files = sorted({ROOT / p for p in listed if p.endswith(".md")})
    public_files = {(ROOT / p).resolve() for p in listed if p}
    failures = []
    checked = 0
    for path in files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig")
        for token in PARSER.parse(text):
            for child in token.children or []:
                value = child.attrGet("href") or child.attrGet("src")
                if value is None:
                    continue
                url = urlsplit(value)
                if url.scheme or url.netloc:
                    continue
                checked += 1
                target = (
                    (path.parent / unquote(url.path)).resolve() if url.path else path
                )
                reason = None
                if target != ROOT and ROOT not in target.parents:
                    reason = "outside repository"
                elif not target.exists():
                    reason = "missing file"
                elif target.is_file() and target not in public_files:
                    reason = "not a publishable repository file"
                elif url.fragment and target.suffix == ".md":
                    if unquote(url.fragment) not in anchors(
                        target.read_text(encoding="utf-8-sig")
                    ):
                        reason = "missing heading"
                if reason:
                    failures.append(f"{path.relative_to(ROOT)} -> {value}: {reason}")
    print(f"Checked {len(files)} Markdown files, {checked} local links")
    for failure in failures:
        print(failure)
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())

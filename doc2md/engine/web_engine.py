"""Web engine: HTML pages and RFC-822 email (.eml) to Markdown."""

from __future__ import annotations

import email
import re
from email import policy
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.encoding import decode_bytes
from doc2md.core.router import FileKind
from doc2md.engine.base import BaseEngine

_ALLOWED_HEADINGS = {f"h{i}" for i in range(1, 7)}
_DROP_TAGS = {"script", "style", "noscript", "template", "iframe", "svg", "form", "nav"}


class WebEngine(BaseEngine):
    name = "web"
    supported_kinds = (FileKind.HTML, FileKind.EML)
    requires_process_isolation = False

    def convert(self, source: Path, options: dict) -> str:
        self.validate_source(source)
        if source.suffix.lower() == ".eml" or _looks_like_eml(source):
            return self._convert_eml(source, options)
        return self._convert_html(source, options)

    def _convert_html(self, source: Path, options: dict) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise EngineUnavailableError(
                "HTML backend missing: pip install 'doc2md[docs]' (beautifulsoup4)"
            ) from exc

        raw = source.read_bytes()
        html = decode_bytes(raw)
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")
        for tag in soup(_DROP_TAGS):
            tag.decompose()
        title_tag = soup.find("title")
        parts = [f"# {(title_tag.get_text(strip=True) or Path(source).stem)}", ""]
        body = soup.body or soup
        rendered = self._render_children(body).strip()
        parts.append(rendered)
        return "\n".join(parts).strip() + "\n"

    def _render_children(self, node) -> str:
        chunks: list[str] = []
        for child in node.children:
            md = self._render_node(child)
            if md:
                chunks.append(md)
        return "\n\n".join(chunks)

    def _render_node(self, node) -> str:
        from bs4 import CData, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag

        if isinstance(node, (Comment, Doctype, Declaration, ProcessingInstruction, CData)):
            return ""
        if isinstance(node, NavigableString):
            text = re.sub(r"\s+", " ", str(node)).strip()
            return text
        if not isinstance(node, Tag):
            return ""
        name = node.name.lower()
        inner = self._render_children(node).strip()

        if name in ("p", "div", "section", "article", "main", "blockquote"):
            if name == "blockquote":
                quoted = "\n".join(f"> {ln}" for ln in inner.splitlines()) if inner else ""
                return quoted
            return inner
        if name in _ALLOWED_HEADINGS:
            level = int(name[1])
            text = node.get_text(" ", strip=True)
            return f"{'#' * level} {text}" if text else ""
        if name == "br":
            return "  \n"
        if name == "hr":
            return "---"
        if name in ("ul", "ol"):
            items = []
            ordered = name == "ol"
            for i, li in enumerate(node.find_all("li", recursive=False), start=1):
                marker = f"{i}." if ordered else "-"
                item_text = self._render_children(li).strip().replace("\n", " ")
                if item_text:
                    items.append(f"{marker} {item_text}")
            return "\n".join(items)
        if name == "table":
            return self._render_table(node)
        if name == "a":
            href = node.get("href") or ""
            text = node.get_text(" ", strip=True) or href
            return f"[{text}]({href})" if href else text
        if name == "img":
            src = node.get("src") or ""
            alt = node.get("alt") or ""
            return f"![{alt}]({src})" if src else ""
        if name in ("strong", "b"):
            return f"**{inner}**" if inner else ""
        if name in ("em", "i"):
            return f"*{inner}*" if inner else ""
        if name == "code":
            return f"`{inner}`" if inner else ""
        if name == "pre":
            return f"```\n{node.get_text().rstrip()}\n```"
        if name in ("tr", "thead", "tbody", "li", "span", "font", "center"):
            return inner
        return inner

    def _render_table(self, table) -> str:
        rows = table.find_all("tr")
        grid = []
        for tr in rows:
            cells = [" ".join(c.get_text(" ", strip=True).split()).replace("|", "\\|")
                     for c in tr.find_all(["th", "td"])]
            if any(cells):
                grid.append(cells)
        if not grid:
            return ""
        width = max(len(r) for r in grid)
        grid = [r + [""] * (width - len(r)) for r in grid]
        lines = [
            "| " + " | ".join(grid[0]) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        lines.extend("| " + " | ".join(r) + " |" for r in grid[1:])
        return "\n".join(lines)

    def _convert_eml(self, source: Path, options: dict) -> str:
        raw = source.read_bytes()
        try:
            message = email.message_from_bytes(raw, policy=policy.default)
        except Exception as exc:
            raise ConversionError(f"Unreadable EML file: {source} ({exc})") from exc

        subject = self._header(message, "Subject")
        sender = self._header(message, "From")
        to = self._header(message, "To")
        date = self._header(message, "Date")

        parts = [f"# {subject or Path(source).name}", ""]
        meta = [f"- **From:** {sender}"]
        if to:
            meta.append(f"- **To:** {to}")
        if date:
            meta.append(f"- **Date:** {date}")
        parts.extend(meta)
        parts.append("")

        body_text, attachments = self._extract_body(message)
        parts.append(body_text.strip())
        if attachments:
            parts.append("")
            parts.append("## Attachments")
            for name in attachments:
                parts.append(f"- {name}")
        return "\n".join(parts).strip() + "\n"

    @staticmethod
    def _header(message, key: str) -> str:
        try:
            value = message.get(key, "")
            return str(value) if value else ""
        except Exception:
            return ""

    def _extract_body(self, message):
        body_plain = None
        body_html = None
        attachments: list[str] = []
        try:
            walk_parts = list(message.walk())
        except Exception:
            walk_parts = [message]
        for part in walk_parts:
            if part.is_multipart():
                continue
            filename = part.get_filename()
            content_type = part.get_content_type()
            disposition = str(part.get_content_disposition() or "")
            if filename or disposition == "attachment":
                attachments.append(filename or f"attachment ({content_type})")
                continue
            if content_type == "text/plain" and body_plain is None:
                body_plain = self._decode_part(part)
            elif content_type == "text/html" and body_html is None:
                body_html = self._decode_part(part)

        if body_plain:
            return body_plain, attachments
        if body_html:
            stripped = self._html_to_text(body_html)
            return stripped, attachments
        return "_(no textual body found)_", attachments

    def _decode_part(self, part) -> str:
        try:
            payload = part.get_content()
            if isinstance(payload, bytes):
                return decode_bytes(payload)
            return str(payload)
        except LookupError:
            raw = part.get_payload(decode=True) or b""
            return decode_bytes(raw)
        except Exception:
            raw = part.get_payload(decode=True) or b""
            return decode_bytes(raw)

    @staticmethod
    def _html_to_text(html: str) -> str:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            lines = []
            for block in soup.stripped_strings:
                lines.append(str(block))
            return "\n\n".join(lines)
        except ImportError:
            return re.sub(r"<[^>]+>", "", html)


def _looks_like_eml(source: Path) -> bool:
    try:
        with open(source, "rb") as fh:
            head = fh.read(2048)
    except OSError:
        return False
    try:
        text = head.decode("utf-8", errors="ignore")
    except Exception:
        return False
    hits = sum(
        1
        for line in text.splitlines()[:20]
        if re.match(r"(?i)^(from|to|subject|date|message-id|mime-version):", line.strip())
    )
    return hits >= 2

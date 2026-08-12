"""Deterministic normalizers for permitted, locally captured CRM archives."""

from __future__ import annotations

import re
import hashlib
from datetime import datetime
import json
from pathlib import Path
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth and data.strip():
            self.parts.append(data.strip())


def html_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return "\n".join(parser.parts)


def _after(text: str, label: str) -> str | None:
    match = re.search(rf"(?:^|\n){re.escape(label)}\n([^\n]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def parse_contact_capture(text: str) -> dict[str, str | None]:
    """Extract stable identity fields from a captured Command contact workspace."""
    name_match = re.search(r"heading \"([^\"]+)\" \[level=2\]", text) or re.search(r"Search Contacts\n([^\n]+)", text)
    if not name_match:
        raise ValueError("Captured contact has no identity heading")
    parts = name_match.group(1).strip().split(maxsplit=1)
    birthday = _after(text, "Birthday")
    anniversary = _after(text, "Home Anniversary")
    parsed_anniversary = None
    if anniversary:
        try:
            parsed_anniversary = datetime.strptime(anniversary, "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
    parsed_birthday = None
    if birthday:
        try:
            parsed_birthday = datetime.strptime(birthday, "%B %d").strftime("%m-%d")
        except ValueError:
            pass
    return {
        "first_name": parts[0],
        "last_name": parts[1] if len(parts) > 1 else "",
        "email": (re.search(r'Primary Email\n- button \"([^\"]+)', text) or [None, _after(text, "Primary Email")])[1],
        "phone": (re.search(r'Primary Phone\n- button \"([^\"]+)', text) or [None, _after(text, "Primary Phone")])[1],
        "stage": "lead",
        "birthday": parsed_birthday,
        "anniversary": parsed_anniversary,
    }


def load_contact_captures(root: Path) -> list[dict[str, str | None]]:
    """Load the one comprehensive capture per archived Command contact."""
    records = []
    for directory in sorted((root / "kw_command_repaired/contacts/sections").glob("*")):
        source = directory / "comprehensive-capture.json"
        payload = json.loads(source.read_text()) if source.exists() else {"ordinal": int(directory.name)}
        ordinal = int(payload["ordinal"])
        section = directory / "timeline.json"
        if not section.exists():
            section = source.parent / "tasks/to_do.json"
        section_payload = json.loads(section.read_text())
        text = section_payload.get("visible_text") or section_payload.get("accessibility_snapshot")
        if not text:
            raise ValueError(f"Captured section {section} has no readable text")
        record = parse_contact_capture(text)
        # Command captures birthdays without a year; keep the source date in audit
        # text rather than inventing a year for a Date column.
        record["birthday"] = None
        records.append(record)
    return records


def parse_task_capture(text: str, status: str) -> list[dict[str, str | None]]:
    """Extract rendered task table rows from a contact section capture."""
    marker = "TASK\nASSIGNED TO\nPRIORITY\nDUE DATE\nCREATED BY\n"
    if marker not in text:
        return []
    lines = [line.strip() for line in text.split(marker, 1)[1].splitlines() if line.strip()]
    rows = []
    for index, line in enumerate(lines):
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", line) and index >= 4:
            title = lines[index - 4]
            if title not in {"TASK", "To Do", "Completed", "Archived"}:
                rows.append({"title": title, "due": line, "status": status})
    return rows


def archive_inventory(root: Path) -> list[dict[str, str | int]]:
    """Return a deterministic, checksum-backed catalog of every source file."""
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        domain = "docusign" if relative.startswith(("docusign_", "docusign/")) else "kw_command"
        suffix = path.suffix.lower().lstrip(".") or "unknown"
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"Cannot read archive artifact: {relative}") from exc
        preview = ""
        if suffix in {"json", "txt", "html", "jsonl", "md", "csv"}:
            preview = raw.decode("utf-8", errors="replace").replace("\x00", " ")[:2000]
        rows.append({
            "source_path": relative,
            "domain": domain,
            "artifact_type": suffix,
            "filename": path.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "text_preview": preview,
        })
    return rows

"""Strict heading-based parser for the supplied Markdown policy format.

Source text stays untrusted data. No execution, prompt interpretation, or SQL
generation occurs here. The small seed sections fit into one embedding each.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

PARSER_VERSION = "headings-v1"
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SECTION_LABEL = re.compile(r"^((?:[A-Z]+-)+\d+)\b")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str
    section: str
    heading: str
    heading_path: tuple[str, ...]
    title: str
    version: str
    status: str
    effective_date: str
    superseded_date: str | None
    line_start: int
    line_end: int
    text: str
    embedding_text: str
    source_sha256: str
    content_sha256: str

    @property
    def label(self) -> tuple[str, str]:
        return self.source, self.section

    def to_dict(self) -> dict:
        return asdict(self)


def parse_policy(path: Path) -> list[Chunk]:
    raw = path.read_bytes()
    lines = raw.decode("utf-8-sig").splitlines()
    headings: list[tuple[int, int, str]] = []
    fence_char, fence_length = "", 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        fence = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence:
            marker = fence.group(1)
            if not fence_char:
                fence_char, fence_length = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char, fence_length = "", 0
            continue
        if not fence_char and (match := HEADING.match(line)):
            headings.append((i, len(match[1]), match[2]))
    if fence_char:
        raise ValueError(f"{path.name}: unclosed code fence")
    if not headings or headings[0][1] != 1 or sum(h[1] == 1 for h in headings) != 1:
        raise ValueError(f"{path.name}: expected one H1 document title")
    if any(line.strip() for line in lines[: headings[0][0]]):
        raise ValueError(f"{path.name}: unsupported content before title")
    header_start = headings[0][0] + 1
    header_end = headings[1][0] if len(headings) > 1 else len(lines)
    metadata = {}
    for line in lines[header_start:header_end]:
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() in metadata:
                raise ValueError(f"{path.name}: duplicate metadata field")
            metadata[key.strip()] = value.strip()
    for key in ["Version", "Effective date", "Status"]:
        if not metadata.get(key):
            raise ValueError(f"{path.name}: missing {key}")
    if metadata["Status"] not in {"CURRENT", "SUPERSEDED"}:
        raise ValueError(f"{path.name}: unknown policy status")
    date.fromisoformat(metadata["Effective date"])
    superseded = metadata.get("Superseded date")
    if metadata["Status"] == "SUPERSEDED" and not superseded:
        raise ValueError(f"{path.name}: superseded policy needs a superseded date")
    if superseded and date.fromisoformat(superseded) < date.fromisoformat(
        metadata["Effective date"]
    ):
        raise ValueError(f"{path.name}: superseded date precedes effective date")
    title = headings[0][2]
    provenance = (
        f"{title}\nVersion: {metadata['Version']}\nStatus: {metadata['Status']}\n"
        f"Effective date: {metadata['Effective date']}"
    )
    if superseded:
        provenance += f"\nSuperseded date: {superseded}"
    chunks, stack, seen = [], [], set()
    for pos, (start, level, heading) in enumerate(headings):
        end = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
        heading_path = tuple(h for _, h in stack)
        if level == 1:
            section = "document status"
            text = "\n".join(lines[start + 1 : end]).strip()
            embedding_text = f"{title}\nDocument status\n{text}"
        else:
            match = SECTION_LABEL.match(heading)
            if not match:
                raise ValueError(f"{path.name}:{start + 1}: section needs a stable label")
            section = match[1]
            text = "\n".join(lines[start + 1 : end]).strip()
            embedding_text = f"{provenance}\n{' > '.join(heading_path[1:])}\n{text}"
        if section in seen:
            raise ValueError(f"{path.name}: duplicate section label {section}")
        seen.add(section)
        content_hash = sha256(embedding_text.encode())
        chunks.append(
            Chunk(
                chunk_id=json_hash([PARSER_VERSION, path.name, section, content_hash]),
                source=path.name,
                section=section,
                heading=heading,
                heading_path=heading_path,
                title=title,
                version=metadata["Version"],
                status=metadata["Status"],
                effective_date=metadata["Effective date"],
                superseded_date=superseded,
                line_start=start + 1,
                line_end=end,
                text=text,
                embedding_text=embedding_text,
                source_sha256=sha256(raw),
                content_sha256=content_hash,
            )
        )
    return chunks


def load_corpus(directory: Path) -> list[Chunk]:
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise ValueError(f"No Markdown policies found in {directory}")
    chunks = [chunk for path in paths for chunk in parse_policy(path)]
    if len({c.label for c in chunks}) != len(chunks):
        raise ValueError("Duplicate source/section labels")
    return chunks


def corpus_manifest(chunks: list[Chunk]) -> dict:
    files = {c.source: c.source_sha256 for c in chunks}
    return {
        "parser_version": PARSER_VERSION,
        "corpus_sha256": json_hash(files),
        "files": files,
        "documents": len(files),
        "chunks": len(chunks),
        "chunk_ids_sha256": json_hash([c.chunk_id for c in chunks]),
    }

"""Read-only navigation over immutable archive files and their ZIP members."""
from __future__ import annotations

import hashlib
import re
import stat
from collections import Counter
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile, ZipInfo

from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMArchiveArtifact

MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_MEMBERS = 5000
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


def canonical_folder(path: str) -> str:
    if path and (
        len(path) > 1000 or "\\" in path
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise HTTPException(422, "Choose a valid archive folder")
    return path


def _content_kind(extension: str) -> str:
    extension = extension.lower()
    if extension == "zip":
        return "document_bundle"
    if extension in {"pdf", "doc", "docx", "odt", "rtf"}:
        return "document"
    if extension in {"html", "htm", "txt", "png", "jpg", "jpeg"}:
        return "source_capture"
    if extension in {"json", "csv", "xml", "xlsx", "xls"}:
        return "data_export"
    return "supporting_file"


def _metadata_statement():
    # The boolean checks byte availability without transferring the private blob.
    return select(
        CRMArchiveArtifact.id, CRMArchiveArtifact.source_path,
        CRMArchiveArtifact.domain, CRMArchiveArtifact.artifact_type,
        CRMArchiveArtifact.filename, CRMArchiveArtifact.sha256,
        CRMArchiveArtifact.size_bytes,
        CRMArchiveArtifact.content_bytes.is_not(None).label("download_available"),
    )


def _artifact_entry(row) -> dict:
    result = dict(row)
    result.update(entry_type="artifact", path=result["source_path"], content_kind=_content_kind(result["artifact_type"]))
    return result


def _page(files: list[dict], *, path: str, query: str, limit: int, offset: int, directories: tuple[str, ...] = ()) -> dict:
    canonical_folder(path)
    prefix = f"{path}/" if path else ""
    query = query.strip()
    matches = [item for item in files if item["path"].startswith(prefix) and query.casefold() in item["path"].casefold()]
    folders: dict[str, dict] = {}
    all_folders: set[str] = set()
    direct: list[dict] = []
    kinds = Counter(item["content_kind"] for item in matches)
    for item in matches:
        relative = item["path"][len(prefix):]
        # Unsafe ZIP names stay visible at the bundle root with downloads blocked.
        unsafe = item.get("unsafe_path", False)
        parts = relative.split("/") if not unsafe else [relative]
        for index in range(1, len(parts)):
            all_folders.add(prefix + "/".join(parts[:index]))
        if len(parts) == 1 or query:
            direct.append(item)
        else:
            folder_path = prefix + parts[0]
            folder = folders.setdefault(folder_path, {"entry_type": "folder", "path": folder_path, "name": parts[0], "file_count": 0})
            folder["file_count"] += 1
    for directory in directories:
        if not directory.startswith(prefix) or query.casefold() not in directory.casefold():
            continue
        parts = directory[len(prefix):].split("/")
        for index in range(1, len(parts) + 1):
            all_folders.add(prefix + "/".join(parts[:index]))
        folder_path = directory if query else prefix + parts[0]
        folders.setdefault(folder_path, {"entry_type": "folder", "path": folder_path, "name": PurePosixPath(folder_path).name, "file_count": sum(item["path"].startswith(folder_path + "/") for item in matches)})
    entries = sorted(folders.values(), key=lambda item: (item["path"].casefold(), item["path"]))
    entries += sorted(direct, key=lambda item: (item["path"].casefold(), item["path"], item.get("member_index", item.get("id", 0))))
    return {
        "path": path, "query": query, "limit": limit, "offset": offset,
        "total": len(entries), "entries": entries[offset:offset + limit],
        "summary": {
            "files": len(matches), "folders": len(all_folders),
            "document_bundles": kinds["document_bundle"], "documents": kinds["document"],
            "source_captures": kinds["source_capture"], "data_exports": kinds["data_export"],
            "supporting_files": kinds["supporting_file"],
            "unavailable_files": sum(not item["download_available"] for item in matches),
        },
    }


async def browse_catalog(db: AsyncSession, *, domain: str | None, path: str, query: str, limit: int, offset: int) -> dict:
    canonical_folder(path)
    # Only small catalog metadata is read for hierarchy/counts; originals are
    # fetched individually and only after an explicit download or bundle open.
    rows = (await db.execute(_metadata_statement())).mappings().all()
    domains = Counter(row["domain"] for row in rows)
    files = [_artifact_entry(row) for row in rows if not domain or row["domain"] == domain]
    page = _page(files, path=path, query=query, limit=limit, offset=offset)
    page["domains"] = dict(domains)
    return page


async def flat_catalog(db: AsyncSession, *, domain: str | None, artifact_type: str | None, limit: int, offset: int) -> dict:
    where = []
    if domain:
        where.append(CRMArchiveArtifact.domain == domain)
    if artifact_type:
        where.append(CRMArchiveArtifact.artifact_type == artifact_type)
    total = (await db.execute(select(func.count()).select_from(CRMArchiveArtifact).where(*where))).scalar_one()
    rows = (await db.execute(
        _metadata_statement().add_columns(CRMArchiveArtifact.text_preview)
        .where(*where).order_by(CRMArchiveArtifact.source_path, CRMArchiveArtifact.id)
        .offset(offset).limit(limit)
    )).mappings().all()
    return {"total": total, "rows": [dict(row) for row in rows]}


async def _original(db: AsyncSession, artifact_id: int, *, bundle: bool = False) -> tuple[dict, bytes]:
    row = (await db.execute(_metadata_statement().where(CRMArchiveArtifact.id == artifact_id))).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Recovered artifact not found")
    if not row["download_available"]:
        raise HTTPException(409, "Recovered artifact bytes are not yet stored internally")
    if bundle and (row["artifact_type"].lower() != "zip" or row["size_bytes"] > MAX_BUNDLE_BYTES):
        raise HTTPException(409, "This file cannot be browsed as a document bundle; download the original instead")
    content = (await db.execute(select(CRMArchiveArtifact.content_bytes).where(CRMArchiveArtifact.id == artifact_id))).scalar_one()
    if content is None or len(content) != row["size_bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
        raise HTTPException(409, "Stored file integrity could not be verified")
    return dict(row), content


def _open_bundle(content: bytes) -> ZipFile:
    try:
        bundle = ZipFile(BytesIO(content))
    except (BadZipFile, ValueError):
        raise HTTPException(409, "The original file is not a readable ZIP bundle") from None
    members = bundle.infolist()
    if len(members) > MAX_BUNDLE_MEMBERS or sum(item.file_size for item in members) > MAX_UNCOMPRESSED_BYTES:
        bundle.close()
        raise HTTPException(409, "Bundle exceeds the safe browsing limit; download the original instead")
    return bundle


def _unsafe_member_path(member: ZipInfo) -> bool:
    try:
        canonical_folder(member.filename.rstrip("/"))
    except HTTPException:
        return True
    return not member.filename or bool(re.match(r"^[A-Za-z]:", member.filename))


def _member_blocker(member: ZipInfo) -> str | None:
    if _unsafe_member_path(member) or stat.S_ISLNK(member.external_attr >> 16):
        return "This member has an unsafe file path or link"
    if member.flag_bits & 1:
        return "This member is encrypted; download the original bundle"
    if member.file_size > MAX_MEMBER_BYTES or member.file_size / max(1, member.compress_size) > MAX_COMPRESSION_RATIO:
        return "This member exceeds the safe download limit; download the original bundle"
    if member.is_dir():
        return "Choose a file inside this folder"
    return None


async def browse_bundle(db: AsyncSession, artifact_id: int, *, path: str, query: str, limit: int, offset: int) -> dict:
    canonical_folder(path)
    row, content = await _original(db, artifact_id, bundle=True)
    with _open_bundle(content) as bundle:
        files = []
        explicit_directories = []
        for index, member in enumerate(bundle.infolist()):
            if member.is_dir():
                if not _unsafe_member_path(member):
                    explicit_directories.append(member.filename.rstrip("/"))
                continue
            blocker = _member_blocker(member)
            extension = PurePosixPath(member.filename).suffix.lstrip(".").lower()
            files.append({
                "entry_type": "member", "member_index": index,
                "path": member.filename, "filename": PurePosixPath(member.filename).name,
                "artifact_type": extension, "content_kind": _content_kind(extension),
                "size_bytes": member.file_size, "download_available": blocker is None,
                "unavailable_reason": blocker, "unsafe_path": _unsafe_member_path(member),
            })
    page = _page(files, path=path, query=query, limit=limit, offset=offset, directories=tuple(explicit_directories))
    page["bundle"] = _artifact_entry(row)
    return page


def _download_response(content: bytes, filename: str, *, archive_sha256: str | None = None) -> Response:
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    filename = "".join(character for character in filename if ord(character) >= 32 and ord(character) != 127)
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "archive-file"
    media_type = {"pdf": "application/pdf", "zip": "application/zip", "csv": "text/csv", "json": "application/json", "txt": "text/plain", "md": "text/plain", "html": "text/html", "png": "image/png"}.get(PurePosixPath(filename).suffix.lstrip(".").lower(), "application/octet-stream")
    headers = {
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
        "Content-Security-Policy": "sandbox", "Referrer-Policy": "no-referrer",
        "X-Content-SHA256": hashlib.sha256(content).hexdigest(),
    }
    if archive_sha256:
        headers["X-Archive-SHA256"] = archive_sha256
    return Response(content=content, media_type=media_type, headers=headers)


async def download_original(db: AsyncSession, artifact_id: int) -> Response:
    row, content = await _original(db, artifact_id)
    return _download_response(content, row["filename"])


async def download_member(db: AsyncSession, artifact_id: int, member_index: int) -> Response:
    row, content = await _original(db, artifact_id, bundle=True)
    with _open_bundle(content) as bundle:
        members = bundle.infolist()
        if member_index < 0 or member_index >= len(members):
            raise HTTPException(404, "Bundle member not found")
        member = members[member_index]
        if blocker := _member_blocker(member):
            raise HTTPException(409, blocker)
        try:
            # Open by ZipInfo identity so duplicate names never resolve to a
            # different file. No member is extracted to the filesystem.
            with bundle.open(member) as source:
                original = source.read(MAX_MEMBER_BYTES + 1)
        except (BadZipFile, RuntimeError, NotImplementedError, ValueError):
            raise HTTPException(409, "Bundle member integrity could not be verified") from None
        if len(original) != member.file_size or len(original) > MAX_MEMBER_BYTES:
            raise HTTPException(409, "Bundle member integrity could not be verified")
    return _download_response(original, member.filename, archive_sha256=row["sha256"])

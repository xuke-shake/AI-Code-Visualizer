import ntpath
import os
import posixpath
import stat
import tempfile
import zlib
from uuid import uuid4
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool
from app.core.config import get_settings
from app.core.exceptions import AppException

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"
}
IGNORED_PARTS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv"}
UPLOAD_READ_CHUNK_SIZE = 1024 * 1024


def _normalise_member_name(raw_name: str) -> tuple[str, bool]:
    """Return a safe POSIX member path and whether the member is a directory."""

    name = raw_name.replace("\\", "/")
    if not name or "\x00" in name:
        raise AppException("ZIP包含空文件名或非法字符，已拒绝上传")
    if name.startswith("/") or name.startswith("//") or ntpath.splitdrive(name)[0]:
        raise AppException("ZIP包含绝对路径或盘符路径，已拒绝上传")

    is_directory = name.endswith("/")
    normalised = posixpath.normpath(name)
    if normalised in {"", "."} or normalised.startswith("../") or normalised == "..":
        raise AppException("ZIP包含非法相对路径，已拒绝上传")
    parts = normalised.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise AppException("ZIP包含未规范化路径，已拒绝上传")
    canonical = f"{normalised}/" if is_directory else normalised
    if name != canonical:
        raise AppException("ZIP包含未规范化路径，已拒绝上传")
    return normalised, is_directory


def _is_symlink(info) -> bool:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(unix_mode)


def validate_zip_file(path: Path) -> dict:
    settings = get_settings()
    try:
        with ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > settings.max_zip_files:
                raise AppException(f"ZIP文件数超过限制: {settings.max_zip_files}")
            accepted = 0
            total_uncompressed = 0
            seen_names: set[str] = set()
            max_member_bytes = settings.max_zip_member_uncompressed_size_mb * 1024 * 1024
            max_total_bytes = settings.max_zip_total_uncompressed_size_mb * 1024 * 1024
            for info in infos:
                name, is_directory = _normalise_member_name(info.filename)
                duplicate_key = name.casefold()
                if duplicate_key in seen_names:
                    raise AppException("ZIP包含重复成员，已拒绝上传")
                seen_names.add(duplicate_key)
                if info.flag_bits & 0x1:
                    raise AppException("ZIP包含加密成员，已拒绝上传")
                if _is_symlink(info):
                    raise AppException("ZIP包含符号链接，已拒绝上传")
                if info.file_size < 0 or info.compress_size < 0:
                    raise AppException("ZIP成员大小非法，已拒绝上传")
                if info.file_size > max_member_bytes:
                    raise AppException(f"ZIP单个文件解压大小超过限制: {settings.max_zip_member_uncompressed_size_mb}MB")
                total_uncompressed += info.file_size
                if total_uncompressed > max_total_bytes:
                    raise AppException(f"ZIP总解压大小超过限制: {settings.max_zip_total_uncompressed_size_mb}MB")
                if info.file_size and info.file_size / max(info.compress_size, 1) > settings.max_zip_compression_ratio:
                    raise AppException("ZIP压缩比超过限制，已拒绝上传")

                # 元数据限制通过后仍实际读取每个文件，触发 zipfile 的 CRC
                # 校验；按成员预算分块读取，避免无界解压。
                if not is_directory:
                    try:
                        read_size = 0
                        with zf.open(info, "r") as member:
                            while True:
                                chunk = member.read(min(UPLOAD_READ_CHUNK_SIZE, max_member_bytes - read_size + 1))
                                if not chunk:
                                    break
                                read_size += len(chunk)
                                if read_size > max_member_bytes:
                                    raise AppException("ZIP成员实际解压大小超过限制")
                    except AppException:
                        raise
                    except (BadZipFile, OSError, RuntimeError, ValueError, zlib.error) as exc:
                        raise AppException("ZIP成员损坏或无法读取") from exc

                parts = set(Path(name).parts)
                if parts & IGNORED_PARTS or is_directory:
                    continue
                suffix = Path(name).suffix.lower()
                if suffix in ALLOWED_EXTENSIONS:
                    accepted += 1
            return {"file_count": len(infos), "accepted_source_files": accepted}
    except BadZipFile as exc:
        raise AppException("ZIP文件损坏或格式不正确") from exc


async def save_upload_zip(upload: UploadFile, user_id: int) -> dict:
    return await run_in_threadpool(save_upload_zip_sync, upload, user_id)


def save_upload_zip_sync(upload: UploadFile, user_id: int) -> dict:
    """One bounded synchronous unit: read/write/fsync/validate/publish/cleanup."""
    settings = get_settings()
    if not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise AppException("仅支持上传.zip代码包")
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    upload_dir = settings.storage_path / "uploads" / str(user_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(upload.filename).name.replace(" ", "_")
    temp_path: Path | None = None
    size_bytes = 0
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".upload-", suffix=".tmp", dir=upload_dir)
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as temp_file:
            while True:
                chunk = upload.file.read(UPLOAD_READ_CHUNK_SIZE)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise AppException(f"上传文件超过{settings.max_upload_size_mb}MB限制")
                temp_file.write(chunk)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        info = validate_zip_file(temp_path)
        object_key = f"uploads/{user_id}/{uuid4().hex}.zip"
        target = settings.storage_path / object_key
        os.replace(temp_path, target)
        temp_path = None
        return {"object_key": object_key, "filename": safe_name, "size_bytes": size_bytes, **info}
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

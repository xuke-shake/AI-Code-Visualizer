import io
import logging
import tokenize
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.models.source_file import SourceFile
from app.tools.hash_utils import sha256_text
from app.tools.zip_safety import _normalise_member_name, IGNORED_PARTS as ZIP_IGNORED_PARTS

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go",
    ".md", ".json", ".yaml", ".yml", ".toml", ".txt",
}
IGNORED_PARTS = ZIP_IGNORED_PARTS

EXT_LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".txt": "text",
}

logger = logging.getLogger(__name__)
_READ_CHUNK_SIZE = 64 * 1024


class SourceInventory(dict):
    """Decoded files plus public diagnostics for files that could not be decoded."""

    def __init__(self):
        super().__init__()
        self.diagnostics: list[dict] = []


class ScannedFiles(list):
    def __init__(self, inventory):
        super().__init__()
        self.inventory = inventory
        self.diagnostics = list(getattr(inventory, "diagnostics", []))


def decode_source(raw: bytes, suffix: str) -> str:
    if suffix == ".py":
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        return raw.decode(encoding)
    return raw.decode("utf-8-sig")


def _line_count(content: str) -> int:
    """按原始文本行定义行数；空文件统一记为 0。"""

    return len(content.splitlines())


def _read_member_bytes(
    archive: ZipFile,
    info,
    total_read: int,
    max_member_bytes: int,
    max_total_bytes: int,
) -> tuple[bytes, int]:
    """流式读取成员，并以实际读取字节数执行单文件/总量限制。

    ``ZipInfo.file_size`` 只用于提前拒绝明显超限的成员；真正的限制依据是
    ``ZipExtFile.read`` 返回的字节数，避免只信任 ZIP 元数据。
    """

    if info.file_size > max_member_bytes:
        raise AppException(f"扫描成员解压大小超过限制: {info.filename}")
    if total_read >= max_total_bytes:
        raise AppException("扫描文件实际读取总大小超过限制")

    member_read = 0
    chunks: list[bytes] = []
    with archive.open(info, "r") as member:
        while True:
            # 多读取一个字节以检测伪造/不可信的 ZIP 元数据；该字节也计入
            # 实际读取量，随后立即拒绝，不会继续展开成员。
            remaining_member = max_member_bytes - member_read
            remaining_total = max_total_bytes - total_read - member_read
            read_size = min(_READ_CHUNK_SIZE, remaining_member + 1, remaining_total + 1)
            chunk = member.read(read_size)
            if not chunk:
                break

            member_read += len(chunk)
            if member_read > max_member_bytes:
                raise AppException(f"扫描成员实际读取大小超过限制: {info.filename}")
            if total_read + member_read > max_total_bytes:
                raise AppException("扫描文件实际读取总大小超过限制")
            chunks.append(chunk)

    return b"".join(chunks), total_read + member_read


def _scan_limits() -> tuple[int, int]:
    settings = get_settings()
    return (
        settings.max_zip_member_uncompressed_size_mb * 1024 * 1024,
        settings.max_zip_total_uncompressed_size_mb * 1024 * 1024,
    )


def scan_zip(db: Session, project_id: int, zip_path: Path) -> list[dict]:
    """遍历ZIP内文件，过滤后写入source_files表，返回(id, path, language, content)列表"""
    inventory = scan_zip_inventory(zip_path)
    results = ScannedFiles(inventory)
    for name, info in inventory.items():
        source_file = SourceFile(
            project_id=project_id, relative_path=name, language=info["language"],
            file_hash=info["hash"], size_bytes=info["size_bytes"],
            line_count=info["line_count"], parse_status="scanned",
        )
        db.add(source_file)
        db.flush()
        results.append({"id": source_file.id, "relative_path": name, **info})
    return results


def scan_zip_inventory(zip_path: Path) -> dict[str, dict]:
    """只读扫描ZIP，不写数据库。返回 {relative_path: {hash, language, content}}"""
    inventory = SourceInventory()
    max_member_bytes, max_total_bytes = _scan_limits()
    total_read = 0

    with ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name, is_directory = _normalise_member_name(info.filename)
            if is_directory:
                continue
            parts = set(Path(name).parts)
            if parts & IGNORED_PARTS:
                continue

            suffix = Path(name).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                continue

            content_bytes, total_read = _read_member_bytes(
                zf,
                info,
                total_read,
                max_member_bytes,
                max_total_bytes,
            )
            try:
                content = decode_source(content_bytes, suffix)
            except (UnicodeError, SyntaxError, LookupError):
                inventory.diagnostics.append({
                    "relative_path": name, "language": EXT_LANG_MAP.get(suffix),
                    "status": "failed", "message": "源码编码声明或文本解码失败",
                })
                continue

            inventory[name] = {
                "hash": sha256_text(content),
                "language": EXT_LANG_MAP.get(suffix),
                "content": content,
                "line_count": _line_count(content),
                "size_bytes": len(content_bytes),
            }

    return inventory

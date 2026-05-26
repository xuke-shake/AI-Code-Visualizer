from pathlib import Path
from zipfile import ZipFile

from sqlalchemy.orm import Session

from app.models.source_file import SourceFile
from app.tools.hash_utils import sha256_text

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go",
    ".md", ".json", ".yaml", ".yml", ".toml", ".txt",
}
IGNORED_PARTS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv"}

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


def scan_zip(db: Session, project_id: int, zip_path: Path) -> list[dict]:
    """遍历ZIP内文件，过滤后写入source_files表，返回(id, path, language, content)列表"""
    results: list[dict] = []

    with ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            name = info.filename.replace("\\", "/")
            parts = set(Path(name).parts)
            if parts & IGNORED_PARTS:
                continue

            suffix = Path(name).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                continue

            content_bytes = zf.read(info)
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue

            source_file = SourceFile(
                project_id=project_id,
                relative_path=name,
                language=EXT_LANG_MAP.get(suffix),
                file_hash=sha256_text(content),
                size_bytes=len(content_bytes),
                line_count=content.count("\n"),
                parse_status="scanned",
            )
            db.add(source_file)
            db.flush()

            results.append({
                "id": source_file.id,
                "relative_path": name,
                "language": EXT_LANG_MAP.get(suffix),
                "content": content,
            })

    return results


def scan_zip_inventory(zip_path: Path) -> dict[str, dict]:
    """只读扫描ZIP，不写数据库。返回 {relative_path: {hash, language, content}}"""
    inventory: dict[str, dict] = {}

    with ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            name = info.filename.replace("\\", "/")
            parts = set(Path(name).parts)
            if parts & IGNORED_PARTS:
                continue

            suffix = Path(name).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                continue

            content_bytes = zf.read(info)
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue

            inventory[name] = {
                "hash": sha256_text(content),
                "language": EXT_LANG_MAP.get(suffix),
                "content": content,
            }

    return inventory

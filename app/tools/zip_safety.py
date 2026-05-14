from pathlib import Path
from zipfile import BadZipFile, ZipFile
from fastapi import UploadFile
from app.core.config import get_settings
from app.core.exceptions import AppException

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"
}
IGNORED_PARTS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv"}


def validate_zip_file(path: Path) -> dict:
    settings = get_settings()
    try:
        with ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > settings.max_zip_files:
                raise AppException(f"ZIP文件数超过限制: {settings.max_zip_files}")
            accepted = 0
            for info in infos:
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or "../" in name or name == "..":
                    raise AppException("ZIP包含非法路径，已拒绝上传")
                parts = set(Path(name).parts)
                if parts & IGNORED_PARTS or info.is_dir():
                    continue
                suffix = Path(name).suffix.lower()
                if suffix in ALLOWED_EXTENSIONS:
                    accepted += 1
            return {"file_count": len(infos), "accepted_source_files": accepted}
    except BadZipFile as exc:
        raise AppException("ZIP文件损坏或格式不正确") from exc


async def save_upload_zip(upload: UploadFile, user_id: int) -> dict:
    settings = get_settings()
    if not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise AppException("仅支持上传.zip代码包")
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    content = await upload.read()
    if len(content) > max_bytes:
        raise AppException(f"上传文件超过{settings.max_upload_size_mb}MB限制")
    upload_dir = settings.storage_path / "uploads" / str(user_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(upload.filename).name.replace(" ", "_")
    object_key = f"uploads/{user_id}/{safe_name}"
    target = settings.storage_path / object_key
    target.write_bytes(content)
    info = validate_zip_file(target)
    return {"object_key": object_key, "filename": safe_name, "size_bytes": len(content), **info}

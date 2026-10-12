from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.exceptions import AppException, NotFoundException
from app.models.diagram import Diagram


class ExportService:
    _DOWNLOAD_SUFFIXES = {".md"}

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def export_diagram(self, diagram: Diagram, fmt: str, filename: str | None = None) -> dict:
        if fmt != "markdown":
            raise AppException(
                "后端尚未支持真实 SVG/PNG/PDF 导出，请使用前端已成功渲染的画布导出",
                code=40030,
            )

        export_dir = self.settings.storage_path / "exports" / str(diagram.project_id) / str(diagram.id)
        export_dir.mkdir(parents=True, exist_ok=True)
        stem = filename or f"diagram_{diagram.id}_v{diagram.version}"
        safe_stem = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in stem)[:128]
        content = f"# {diagram.title}\n\n```mermaid\n{diagram.mermaid_code}\n```\n"
        suffix = "md"
        # 以确切 diagram_id 隔离同项目不同图表的同名导出。
        object_key = f"exports/{diagram.project_id}/{diagram.id}/{safe_stem}.{suffix}"
        target = self.settings.storage_path / object_key
        target.write_text(content, encoding="utf-8")
        return {
            "download_url": f"/api/diagrams/{diagram.id}/export/{target.name}",
            "object_key": object_key,
            "format": fmt,
        }

    def resolve_export_path(self, diagram: Diagram, filename: str) -> Path:
        """解析指定图表的导出文件，并拒绝越界或非导出文件路径。

        导出目录不再通过静态文件服务公开。下载请求只能在当前图表所属
        项目的导出目录内读取单个文件；解析后的真实路径仍需位于该目录，
        因此符号链接和 ``..`` 路径也不会把请求带到 storage 外部。
        """

        if not filename or Path(filename).name != filename:
            raise NotFoundException("导出文件不存在")

        export_dir = (self.settings.storage_path / "exports" / str(diagram.project_id) / str(diagram.id)).resolve()
        candidate = (export_dir / filename).resolve()
        try:
            candidate.relative_to(export_dir)
        except ValueError as exc:
            raise NotFoundException("导出文件不存在") from exc

        if candidate.suffix.lower() not in self._DOWNLOAD_SUFFIXES or not candidate.is_file() or candidate.is_symlink():
            raise NotFoundException("导出文件不存在")
        current = export_dir
        for part in candidate.relative_to(export_dir).parts:
            current = current / part
            if current.is_symlink():
                raise NotFoundException("导出文件不存在")
        return candidate

    @staticmethod
    def media_type(path: Path) -> str:
        return {".md": "text/markdown; charset=utf-8"}.get(
            path.suffix.lower(), "application/octet-stream"
        )

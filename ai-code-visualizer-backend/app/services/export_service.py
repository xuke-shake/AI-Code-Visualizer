from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.diagram import Diagram


class ExportService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def export_diagram(self, diagram: Diagram, fmt: str, filename: str | None = None) -> dict:
        export_dir = self.settings.storage_path / "exports" / str(diagram.project_id)
        export_dir.mkdir(parents=True, exist_ok=True)
        stem = filename or f"diagram_{diagram.id}_v{diagram.version}"
        safe_stem = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in stem)[:128]
        if fmt == "markdown":
            content = f"# {diagram.title}\n\n```mermaid\n{diagram.mermaid_code}\n```\n"
            suffix = "md"
        elif fmt == "svg":
            escaped = diagram.mermaid_code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            content = f"<svg xmlns='http://www.w3.org/2000/svg' width='800' height='300'><text x='20' y='40'>{escaped}</text></svg>"
            suffix = "svg"
        else:
            # PNG/PDF真实导出后续由图表负责人接入无头浏览器或前端导出。
            content = f"暂未接入真实{fmt.upper()}渲染，当前导出Mermaid源码：\n{diagram.mermaid_code}\n"
            suffix = "txt"
        object_key = f"exports/{diagram.project_id}/{safe_stem}.{suffix}"
        target = self.settings.storage_path / object_key
        target.write_text(content, encoding="utf-8")
        return {"download_url": f"/static/{object_key}", "object_key": object_key, "format": fmt}

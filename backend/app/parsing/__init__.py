import logging

from pathlib import Path

from sqlalchemy.orm import Session

from app.parsing.chunker import chunk_and_save
from app.parsing.dependency_analyzer import extract_imports
from app.parsing.file_scanner import scan_zip
from app.parsing.symbol_extractor import extract_and_save
from app.parsing.tree_parser import parse_source
from app.models.source_file import SourceFile

logger = logging.getLogger(__name__)


class ParseStats(dict):
    """五项统一统计之外，携带不进入统计键的单文件诊断。"""

    def __init__(self) -> None:
        super().__init__(
            source_files=0,
            python_files=0,
            symbols=0,
            chunks=0,
            dependencies=0,
        )
        self.diagnostics: list[dict[str, str]] = []
        self.inventory: dict = {}

    def record_diagnostic(self, diagnostic: dict[str, str]) -> None:
        for index, current in enumerate(self.diagnostics):
            if current.get("relative_path") == diagnostic.get("relative_path"):
                self.diagnostics[index] = {**current, **diagnostic}
                return
        self.diagnostics.append(diagnostic)


def _set_parse_status(db: Session, source_file_id: int, status: str) -> None:
    source_file = db.get(SourceFile, source_file_id)
    if source_file is not None:
        source_file.parse_status = status


def parse_project(db: Session, project_id: int, zip_path: Path) -> dict:
    """扫描ZIP、解析符号、切分代码块、提取依赖。返回统计信息。"""
    stats = ParseStats()

    # 1. 扫描 ZIP
    all_files = scan_zip(db, project_id, zip_path)
    stats.inventory = all_files.inventory
    stats.diagnostics.extend(all_files.diagnostics)
    stats["source_files"] = len(all_files)

    # 2. 解析 Python 符号 & 切块
    python_files = [f for f in all_files if f["language"] == "python"]
    stats["python_files"] = len(python_files)

    known_files = {
        row.relative_path: row.id
        for row in db.query(SourceFile).filter(SourceFile.project_id == project_id).all()
    }
    usable_python_files = [
        f for f in python_files
        if db.get(SourceFile, f["id"]) is not None
        and db.get(SourceFile, f["id"]).parse_status not in {"failed", "partial"}
    ]
    for f in usable_python_files:
        diagnostic = {
            "relative_path": f["relative_path"],
            "language": f["language"],
            "status": "parsed",
            "message": "解析成功",
        }
        try:
            symbols = parse_source(f["content"])
        except Exception as exc:
            _set_parse_status(db, f["id"], "failed")
            diagnostic.update(status="failed", message="单文件解析失败")
            stats.record_diagnostic(diagnostic)
            logger.exception("单文件解析失败 path=%s", f["relative_path"], exc_info=exc)
            continue

        if not symbols:
            status = "empty" if not f["content"].splitlines() else "parsed"
            message = "空文件，无可提取符号" if status == "empty" else "未发现可提取符号"
            _set_parse_status(db, f["id"], status)
            diagnostic.update(status=status, message=message)
            stats.record_diagnostic(diagnostic)
            if status == "parsed":
                chunks = chunk_and_save(db, project_id, f["id"], f["content"], symbols)
                stats["chunks"] += len(chunks)
            continue

        savepoint = db.begin_nested()
        try:
            extract_and_save(db, project_id, f["id"], symbols)
            chunks = chunk_and_save(db, project_id, f["id"], f["content"], symbols)
        except Exception as exc:
            savepoint.rollback()
            _set_parse_status(db, f["id"], "failed")
            diagnostic.update(status="failed", message="单文件索引写入失败")
            stats.record_diagnostic(diagnostic)
            logger.exception("单文件索引写入失败 path=%s", f["relative_path"], exc_info=exc)
            continue

        savepoint.commit()
        stats["chunks"] += len(chunks)
        stats["symbols"] += len(symbols)
        _set_parse_status(db, f["id"], "parsed")
        diagnostic["message"] = f"解析成功，提取符号 {len(symbols)} 个"
        stats.diagnostics.append(diagnostic)

    # 3. 提取 import 依赖（需要等所有文件入库后才能跨文件匹配）
    for f in usable_python_files:
        current_file = db.get(SourceFile, f["id"])
        if current_file is None or current_file.parse_status in {"failed", "partial"}:
            continue
        try:
            dep_ids = extract_imports(db, project_id, f["id"], f["content"], known_files=known_files)
        except Exception as exc:
            _set_parse_status(db, f["id"], "partial")
            stats.record_diagnostic(
                {
                    "relative_path": f["relative_path"],
                    "language": f["language"],
                    "status": "partial",
                    "message": "依赖提取失败",
                }
            )
            logger.exception("单文件依赖提取失败 path=%s", f["relative_path"], exc_info=exc)
            continue
        stats["dependencies"] += len(dep_ids)

    for f in all_files:
        if f["language"] != "python":
            _set_parse_status(db, f["id"], "skipped")
            stats.record_diagnostic(
                {
                    "relative_path": f["relative_path"],
                    "language": f["language"],
                    "status": "skipped",
                    "message": "当前解析器不支持此语言",
                }
            )

    return stats

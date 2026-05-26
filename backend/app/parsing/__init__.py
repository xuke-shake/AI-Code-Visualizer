from pathlib import Path

from sqlalchemy.orm import Session

from app.parsing.chunker import chunk_and_save
from app.parsing.dependency_analyzer import extract_imports
from app.parsing.file_scanner import scan_zip
from app.parsing.symbol_extractor import extract_and_save
from app.parsing.tree_parser import parse_source


def parse_project(db: Session, project_id: int, zip_path: Path) -> dict:
    """扫描ZIP、解析符号、切分代码块、提取依赖。返回统计信息。"""
    stats = {"source_files": 0, 
             "python_files": 0, 
             "symbols": 0, "chunks": 0, 
             "dependencies": 0}

    # 1. 扫描 ZIP
    all_files = scan_zip(db, project_id, zip_path)
    stats["source_files"] = len(all_files)

    # 2. 解析 Python 符号 & 切块
    python_files = [f for f in all_files if f["language"] == "python"]
    stats["python_files"] = len(python_files)

    for f in python_files:
        try:
            symbols = parse_source(f["content"])
        except Exception as exc:
            print(f"  [skip] {f['relative_path']}: parse error - {exc}")
            continue

        if not symbols:
            continue

        extract_and_save(db, project_id, f["id"], symbols)
        stats["symbols"] += len(symbols)

        chunk_and_save(db, project_id, f["id"], f["content"], symbols)
        stats["chunks"] += len(symbols)

    # 3. 提取 import 依赖（需要等所有文件入库后才能跨文件匹配）
    for f in python_files:
        try:
            dep_ids = extract_imports(db, project_id, f["id"], f["content"])
        except Exception as exc:
            print(f"  [skip deps] {f['relative_path']}: {exc}")
            continue
        stats["dependencies"] += len(dep_ids)

    return stats

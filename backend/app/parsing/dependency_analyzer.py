import ast

from sqlalchemy.orm import Session
from app.models.dependency import Dependency
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from sqlalchemy import or_


# 解析代码里所有的 import，生成依赖记录并存进数据库，返回这些依赖的 ID 列表。

def extract_imports(
    db: Session,
    project_id: int,
    source_file_id: int,
    code: str,
    known_files: dict[str, int] | None = None,    #文件缓存
) -> list[int]:
    """解析 import 语句，写入 dependencies 表，返回 dependency ID 列表。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    ids: list[int] = []
    if known_files is None:
        known_files = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target_file_id = _resolve_file(alias.name, db, project_id, known_files)
                target_symbol_id = _resolve_symbol(db, project_id, target_file_id, alias.name)
                dep = Dependency(
                    project_id=project_id,
                    source_file_id=source_file_id,
                    target_file_id=target_file_id,
                    target_symbol_id=target_symbol_id,
                    relation_type="imports",
                    confidence=70 if target_file_id else 50,
                    evidence=f"import {alias.name}",
                )
                db.add(dep)
                db.flush() 
                ids.append(dep.id)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                target_file_id = _resolve_file(module, db, project_id, known_files)
                target_symbol_id = _resolve_symbol(db, project_id, target_file_id, alias.name)
                dep = Dependency(
                    project_id=project_id,
                    source_file_id=source_file_id,
                    target_file_id=target_file_id,
                    target_symbol_id=target_symbol_id,
                    relation_type="imports",
                    confidence=70 if target_file_id else 50,
                    evidence=f"from {module} import {alias.name}",
                )
                db.add(dep)
                db.flush()
                ids.append(dep.id)

    return ids



def _resolve_symbol(db: Session, project_id: int, target_file_id: int | None, symbol_name: str) -> int | None:
    """在目标文件中查找同名符号，返回 symbol ID。"""
    if not target_file_id:
        return None
    found = db.query(Symbol).filter(
        Symbol.project_id == project_id,
        Symbol.file_id == target_file_id,
        Symbol.name == symbol_name,
    ).first()
    return found.id if found else None


def _resolve_file(
    module_path: str, db: Session, project_id: int, cache: dict[str, int]
) -> int | None:
    """尝试将模块路径匹配到 source_files 表中的文件。"""
    if not module_path:
        return None
    if module_path in cache:
        return cache[module_path]

    # module_path 如 "models.doctor" → 匹配 relative_path 含 "models/doctor.py" 或 "models\\doctor.py"
    candidates = [
        module_path.replace(".", "/") + ".py",      #Linux / Mac
        module_path.replace(".", "\\") + ".py",     #Windows
        module_path.replace(".", "/") + "/__init__.py",    
    ]
    for candidate in candidates:
       
        found = db.query(SourceFile).filter(
            SourceFile.project_id == project_id,
            or_(
                SourceFile.relative_path.endswith(f'/{candidate}'),
                SourceFile.relative_path.endswith(f'\\{candidate}')
            )
        ).first()
        if found:
            cache[module_path] = found.id
            return found.id

    return None

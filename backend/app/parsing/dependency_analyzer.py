"""Static imports at the ZIP logical root; uncertain runtime bindings stay unresolved."""
import ast
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.models.dependency import Dependency
from app.models.source_file import SourceFile
from app.models.symbol import Symbol


def extract_imports(db: Session, project_id: int, source_file_id: int, code: str,
                    known_files: dict[str, int] | None = None) -> list[int]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    cache = known_files if known_files is not None else {}
    source = db.get(SourceFile, source_file_id)
    source_path = source.relative_path if source else ""
    ids = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _resolve_file(alias.name, db, project_id, cache)
                dep = Dependency(project_id=project_id, source_file_id=source_file_id,
                                 target_file_id=target, target_symbol_id=None,
                                 relation_type="imports", confidence=70 if target else 50,
                                 evidence=f"import {alias.name}")
                db.add(dep)
                db.flush()
                ids.append(dep.id)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                target, symbol = _resolve_from_file(module, node.level, alias.name, source_path, db, project_id, cache)
                dep = Dependency(project_id=project_id, source_file_id=source_file_id,
                                 target_file_id=target, target_symbol_id=symbol,
                                 relation_type="imports", confidence=70 if target else 50,
                                 evidence=f"from {'.' * node.level}{module} import {alias.name}")
                db.add(dep)
                db.flush()
                ids.append(dep.id)
    return ids


def _module_index(db: Session, project_id: int, cache: dict) -> dict[str, int]:
    if "__module_index__" not in cache:
        rows = db.query(SourceFile).filter_by(project_id=project_id, language="python").all()
        index, ambiguous = {}, set()
        for row in rows:
            path = row.relative_path.replace("\\", "/").strip("/")
            if path in index:
                ambiguous.add(path)
            index[path] = row.id
        cache["__module_index__"] = {path: value for path, value in index.items() if path not in ambiguous}
    return cache["__module_index__"]


def _resolve_file(module_path: str, db: Session, project_id: int, cache: dict, source_path: str = "") -> int | None:
    if not module_path:
        return None
    index = _module_index(db, project_id, cache)
    stem = module_path.replace(".", "/")
    parts = stem.split("/")
    if any(f"{'/'.join(parts[:length])}.py" in index for length in range(1, len(parts))):
        return None
    matches = {index[path] for path in (f"{stem}.py", f"{stem}/__init__.py") if path in index}
    return next(iter(matches)) if len(matches) == 1 else None


def _bindings(db: Session, project_id: int, cache: dict) -> dict:
    if "__bindings__" in cache:
        return cache["__bindings__"]
    result = {}
    modules = db.query(CodeChunk).filter_by(project_id=project_id, chunk_type="module").all()
    for chunk in modules:
        names, uncertain = {}, False
        try:
            body = ast.parse(chunk.content).body
        except SyntaxError:
            result[chunk.file_id] = ({}, True)
            continue
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names[statement.name] = statement
                uncertain |= statement.name == "__getattr__"
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    uncertain |= alias.name == "*"
                    names[alias.asname or alias.name.split(".")[0]] = None
            elif isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                if isinstance(statement, ast.AnnAssign) and statement.value is None:
                    continue
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets:
                    for child in ast.walk(target):
                        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                            names[child.id] = None
            elif isinstance(statement, ast.Delete):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        names.pop(target.id, None)
            elif isinstance(statement, (ast.If, ast.Try, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Match)):
                # Optional/reassigned exports cannot be a definite module target.
                uncertain = True
        result[chunk.file_id] = (names, uncertain)
    cache["__bindings__"] = result
    return result


def _resolve_symbol(db: Session, project_id: int, target_file_id: int | None,
                    symbol_name: str, definition=None) -> int | None:
    if target_file_id is None:
        return None
    query = db.query(Symbol).filter_by(project_id=project_id, file_id=target_file_id,
                                      name=symbol_name, qualified_name=symbol_name)
    query = query.filter(Symbol.kind.in_(("function", "class")))
    if definition is not None:
        start = min([definition.lineno] + [item.lineno for item in definition.decorator_list])
        query = query.filter(Symbol.start_line == start)
    found = query.order_by(Symbol.start_line.desc(), Symbol.id.desc()).first()
    return found.id if found else None


def _resolve_from_file(module: str, level: int, imported_name: str, source_path: str,
                       db: Session, project_id: int, cache: dict) -> tuple[int | None, int | None]:
    package = list(PurePosixPath(source_path.replace("\\", "/")).parts[:-1])
    if level:
        if level > len(package):
            return None, None
        parts = package[:len(package) - level + 1] + (module.split(".") if module else [])
    else:
        parts = module.split(".") if module else []
    container_name = ".".join(parts)
    container = _resolve_file(container_name, db, project_id, cache)
    bindings = _bindings(db, project_id, cache)
    if container is not None:
        names, uncertain = bindings.get(container, ({}, False))
        if uncertain:
            return None, None
        if imported_name in names:
            definition = names[imported_name]
            symbol = _resolve_symbol(db, project_id, container, imported_name, definition) if definition is not None else None
            return container, symbol
        if imported_name == "*":
            return container, None
    index = _module_index(db, project_id, cache)
    stem = container_name.replace(".", "/")
    # A normal .py module cannot own submodules. Namespace packages require
    # actual descendants and no competing normal module at the same name.
    package_confirmed = bool(stem and f"{stem}.py" not in index and any(path.startswith(stem + "/") for path in index))
    if package_confirmed and imported_name != "*":
        nested = _resolve_file(f"{container_name}.{imported_name}", db, project_id, cache)
        if nested is not None:
            return nested, None
    return None, None

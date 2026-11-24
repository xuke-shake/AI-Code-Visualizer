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


# ---- 函数级调用关系 ----

def _callee_name(func) -> str | None:
    """提取调用目标的名称：Name -> 'foo'，Attribute 链 -> 'obj.foo'；复杂表达式返回 None。"""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
            return ".".join(reversed(parts))
    return None


def _owner_symbol(lineno: int, file_symbols: list[Symbol]) -> Symbol | None:
    """把调用归属到行号区间覆盖它的函数/方法符号（区间互不重叠）。"""
    for s in file_symbols:
        if s.start_line is not None and s.end_line is not None and s.start_line <= lineno <= s.end_line:
            return s
    return None


def _import_maps(tree) -> tuple[dict, dict]:
    """返回 (from_imports, module_imports)。

    from_imports: 本地名 -> (module, level, imported_name)
    module_imports: 本地别名 -> 完整模块点路径
    """
    from_imports: dict[str, tuple[str, int, str]] = {}
    module_imports: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                from_imports[alias.asname or alias.name] = (node.module or "", node.level, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module_imports[alias.asname or alias.name.split(".")[0]] = alias.name
    return from_imports, module_imports


def _find_symbol(db: Session, project_id: int, file_id: int, name: str) -> Symbol | None:
    return (
        db.query(Symbol)
        .filter_by(project_id=project_id, file_id=file_id)
        .filter((Symbol.qualified_name == name) | (Symbol.name == name))
        .filter(Symbol.kind.in_(("function", "method")))
        .order_by(Symbol.start_line, Symbol.id)
        .first()
    )


def _resolve_callee(callee: str, owner: Symbol, source_path: str, db: Session, project_id: int,
                    cache: dict, same_file: dict[str, Symbol], from_imports: dict, module_imports: dict) -> tuple[int | None, int | None] | None:
    """把被调名解析为 (target_file_id, target_symbol_id)；无法解析返回 None。"""
    first, dot, rest = callee.partition(".")

    # self/cls 方法调用 -> 当前类的方法
    if first in ("self", "cls"):
        if owner.qualified_name and "." in owner.qualified_name:
            cls_name = owner.qualified_name.rsplit(".", 1)[0]
            sym = same_file.get(f"{cls_name}.{rest}")
            if sym is not None and sym.kind == "method":
                return sym.file_id, sym.id
        return None

    # 同文件符号（函数名 / Class.method）
    sym = same_file.get(callee)
    if sym is not None and sym.kind in ("function", "method"):
        return sym.file_id, sym.id

    # from ... import name 后直接调用 name()
    if dot == "" and callee in from_imports:
        module, level, imported = from_imports[callee]
        target_file, target_sym = _resolve_from_file(module, level, imported, source_path, db, project_id, cache)
        if target_file is None and target_sym is None:
            return None
        return target_file, target_sym

    # import module 后 module.attr() 调用
    if dot and first in module_imports:
        full_module = module_imports[first]
        module_file = _resolve_file(full_module, db, project_id, cache, source_path)
        if module_file is None:
            return None
        attr = callee[len(first) + 1:]
        target_sym = _find_symbol(db, project_id, module_file, attr)
        return module_file, target_sym.id if target_sym is not None else None

    return None


def extract_calls(db: Session, project_id: int, source_file_id: int, code: str,
                  known_files: dict[str, int] | None = None) -> list[int]:
    """识别函数/方法体内的函数调用，写入 calls 依赖边，返回依赖 ID 列表。

    只记录能解析到项目内函数/方法符号的调用（内置函数与外部未解析调用忽略）。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    cache = known_files if known_files is not None else {}
    source = db.get(SourceFile, source_file_id)
    source_path = source.relative_path if source else ""

    file_symbols = (
        db.query(Symbol)
        .filter_by(project_id=project_id, file_id=source_file_id)
        .filter(Symbol.kind.in_(("function", "method")))
        .all()
    )
    same_file = {
        s.qualified_name or s.name: s
        for s in db.query(Symbol).filter_by(project_id=project_id, file_id=source_file_id).all()
    }
    from_imports, module_imports = _import_maps(tree)

    ids: list[int] = []
    seen: set[tuple[int | None, int | None]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _callee_name(node.func)
        if not callee:
            continue
        owner = _owner_symbol(node.lineno, file_symbols)
        if owner is None:
            continue
        target = _resolve_callee(callee, owner, source_path, db, project_id, cache,
                                 same_file, from_imports, module_imports)
        if target is None:
            continue
        target_file_id, target_symbol_id = target
        if target_file_id is None and target_symbol_id is None:
            continue
        key = (owner.id, target_symbol_id, target_file_id)
        if key in seen:
            continue
        seen.add(key)
        dep = Dependency(
            project_id=project_id,
            source_symbol_id=owner.id,
            target_symbol_id=target_symbol_id,
            source_file_id=source_file_id,
            target_file_id=target_file_id,
            relation_type="calls",
            confidence=90 if target_symbol_id is not None else 70,
            evidence=f"{callee}()",
        )
        db.add(dep)
        db.flush()
        ids.append(dep.id)

    return ids

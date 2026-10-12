"""从已有完整模块和符号块选取有行号的证据；不改变持久化索引。"""
from __future__ import annotations

import ast
import re
import symtable
import textwrap
from collections import defaultdict, deque
from dataclasses import dataclass


OMISSION_NOTICE = "# [上下文省略：预算或相关性筛选省略了部分源码；省略不表示源码不存在，不可据此推断未展示逻辑。]"
INCOMPLETE_NOTICE = "# [证据不足：目标符号超出预算，仅展示有定位的部分行，不能视为完整函数或完整业务证据。]"


@dataclass(frozen=True)
class Fragment:
    path: str
    label: str
    start: int
    lines: tuple[str, ...]
    priority: tuple
    symbol: bool = False

    def render(self) -> str:
        end = self.start + len(self.lines) - 1
        return f"--- 文件路径: {self.path} | 行 {self.start}-{end} | {self.label} ---\n" + "\n".join(self.lines)


def _names(code: str, scope=None) -> set[str]:
    """仅收集全局读取；局部、参数、闭包绑定不成为同名模块依赖。"""
    try:
        root = scope if scope is not None else symtable.symtable(textwrap.dedent(code), "<context>", "exec")
        names, pending = set(), [root]
        while pending:
            current = pending.pop()
            names.update(s.get_name() for s in current.get_symbols() if s.is_referenced() and s.is_global())
            pending.extend(current.get_children())
        return names
    except (SyntaxError, ValueError, RecursionError):
        # 无法可靠解析时保守保留；预算层仍披露省略和证据不足。
        return set(re.findall(r"[A-Za-z_]\w*", code))


def _definition_heads(node):
    heads = node.decorator_list[:]
    if isinstance(node, ast.ClassDef):
        return heads + node.bases + [kw.value for kw in node.keywords]
    heads += node.args.defaults + [d for d in node.args.kw_defaults if d is not None]
    args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
    args += [a for a in (node.args.vararg, node.args.kwarg) if a is not None]
    heads += [a.annotation for a in args if a.annotation is not None]
    if node.returns is not None:
        heads.append(node.returns)
    return heads


def _expression_reads(expression):
    """分别返回表达式本层读取与 lambda/推导式内层的外部读取；只建立符号表。"""
    try:
        code = "def __context_expression__():\n    return (" + ast.unparse(expression) + ")\n"
        scope = symtable.symtable(code, "<context>", "exec").get_children()[0]
        outer = {s.get_name() for s in scope.get_symbols() if s.is_referenced() and s.is_global()}
        inner = set().union(*(_names("", scope=child) for child in scope.get_children())) if scope.get_children() else set()
        return outer, inner
    except (SyntaxError, ValueError, RecursionError):
        # 编译无法确定作用域时保守保留候选，不执行表达式。
        return {n.id for n in ast.walk(expression) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}, set()


def _is_module_read(scope, name, bound=()):
    try:
        symbol = scope.lookup(name)
    except KeyError:
        return True
    return symbol.is_global() or (scope.get_type() == "class" and symbol.is_local() and name not in bound)


def _class_reads(node, scope, outer_scope):
    """类体先读后写；分支汇合只保留确定绑定，不把方法/表达式内层当类局部。"""
    dependencies, before_definitions = set(), {}

    def read(expression, bound):
        """按求值顺序传递确定绑定；未必执行的分支只收集证据。"""
        if expression is None:
            return
        if isinstance(expression, ast.Name):
            if _is_module_read(scope, expression.id, bound):
                dependencies.add(expression.id)
        elif isinstance(expression, ast.NamedExpr):
            read(expression.value, bound)
            write_target(expression.target, bound)
        elif isinstance(expression, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            if isinstance(expression, ast.Lambda):
                # 默认值在类体求值，lambda 本体在独立作用域中运行。
                for default in expression.args.defaults + [d for d in expression.args.kw_defaults if d is not None]:
                    read(default, bound)
            else:
                # 只有最外层 iterable 在当前类体求值；推导式局部不外泄。
                read(expression.generators[0].iter, bound)
            _, inner = _expression_reads(expression)
            dependencies.update(name for name in inner if _is_module_read(outer_scope, name))
        elif isinstance(expression, ast.IfExp):
            read(expression.test, bound)
            left, right = set(bound), set(bound)
            read(expression.body, left)
            read(expression.orelse, right)
            bound.clear()
            bound.update(left & right)
        elif isinstance(expression, ast.BoolOp):
            read(expression.values[0], bound)
            conditional = set(bound)
            for value in expression.values[1:]:
                read(value, conditional)  # 后续操作数可能短路；沿执行路径传递，不发布。
        elif isinstance(expression, ast.Compare):
            read(expression.left, bound)
            read(expression.comparators[0], bound)
            conditional = set(bound)
            for comparator in expression.comparators[1:]:
                read(comparator, conditional)
        elif isinstance(expression, ast.Dict):
            for key, value in zip(expression.keys, expression.values):
                read(key, bound)
                read(value, bound)
        else:
            for child in ast.iter_child_nodes(expression):
                read(child, bound)

    def write_target(target, bound, delete=False):
        """逐个目标从左到右处理；下标/属性读取不冒充名字绑定。"""
        if isinstance(target, ast.Name):
            if delete:
                bound.discard(target.id)
            else:
                bound.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                write_target(item, bound, delete)
        elif isinstance(target, ast.Starred):
            write_target(target.value, bound, delete)
        elif isinstance(target, ast.Attribute):
            read(target.value, bound)
        elif isinstance(target, ast.Subscript):
            read(target.value, bound)
            read(target.slice, bound)
        else:
            read(target, bound)

    def block(statements, incoming):
        bound = set(incoming)
        for stmt in statements:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                before_definitions[(stmt.name, stmt.lineno)] = frozenset(bound)
                for head in _definition_heads(stmt):
                    read(head, bound)
                bound.add(stmt.name)
            elif isinstance(stmt, ast.Assign):
                read(stmt.value, bound)
                for target in stmt.targets:
                    write_target(target, bound)
            elif isinstance(stmt, ast.AnnAssign):
                # 无 RHS 的 Name 不绑定；表达式目标仍求值对象/下标。
                if stmt.value is not None:
                    read(stmt.value, bound)
                    write_target(stmt.target, bound)
                elif isinstance(stmt.target, (ast.Attribute, ast.Subscript)):
                    write_target(stmt.target, bound)  # 仅读取目标表达式，没有最终写入。
                read(stmt.annotation, bound)
            elif isinstance(stmt, ast.Assert):
                read(stmt.test, bound)
                # 消息只在失败并抛出异常的路径求值，其绑定不进入后续正常路径。
                read(stmt.msg, set(bound))
            elif isinstance(stmt, ast.AugAssign):
                read(stmt.target, bound)
                read(stmt.value, bound)
                if isinstance(stmt.target, ast.Name):
                    bound.add(stmt.target.id)  # 对象/下标已经求值，不能在 RHS 后再读一次。
            elif isinstance(stmt, ast.Delete):
                for target in stmt.targets:
                    write_target(target, bound, delete=True)
            elif isinstance(stmt, ast.If):
                read(stmt.test, bound)
                bound = block(stmt.body, bound) & block(stmt.orelse, bound)
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                read(stmt.test if isinstance(stmt, ast.While) else stmt.iter, bound)
                body_bound = set(bound)
                if not isinstance(stmt, ast.While):
                    write_target(stmt.target, body_bound)
                block(stmt.body, body_bound)
                block(stmt.orelse, bound)
                # 零次循环/提前退出均可能发生，不发布循环内新增绑定。
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                for item in stmt.items:
                    read(item.context_expr, bound)
                    if item.optional_vars is not None:
                        write_target(item.optional_vars, bound)
                bound = block(stmt.body, bound)
            elif isinstance(stmt, (ast.Try, ast.TryStar)):
                paths = [block(stmt.orelse, block(stmt.body, bound))]
                for handler in stmt.handlers:
                    handler_bound = set(bound)
                    if handler.type is not None:
                        read(handler.type, handler_bound)
                    if handler.name:
                        handler_bound.add(handler.name)
                    handler_bound = block(handler.body, handler_bound)
                    if handler.name:
                        handler_bound.discard(handler.name)
                    paths.append(handler_bound)
                bound = block(stmt.finalbody, set.intersection(*paths))
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                bound.update(alias.asname or (alias.name.split(".")[0] if isinstance(stmt, ast.Import) else alias.name)
                             for alias in stmt.names if alias.name != "*")
            elif isinstance(stmt, ast.Match):
                read(stmt.subject, bound)
                for case in stmt.cases:
                    case_bound = set(bound)
                    if case.guard is not None:
                        read(case.guard, case_bound)
                    block(case.body, case_bound)  # 分支的 NamedExpr 不发布为确定绑定。
            else:
                for child in ast.iter_child_nodes(stmt):
                    if isinstance(child, ast.expr):
                        read(child, bound)
        return bound

    block(node.body, set())
    return dependencies, before_definitions


def _fragments(source_files, symbols, chunks, prompt):
    terms = {term.lower() for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", prompt or "")}
    fragments, modules = [], {}
    symbols_by_file, chunks_by_file = defaultdict(list), defaultdict(list)
    for symbol in symbols:
        symbols_by_file[symbol.file_id].append(symbol)
    for chunk in chunks:
        chunks_by_file[chunk.file_id].append(chunk)

    for source_file in source_files:
        path = source_file.relative_path
        file_symbols, file_chunks = symbols_by_file[source_file.id], chunks_by_file[source_file.id]
        chunks_by_range = {
            (chunk.symbol_name, chunk.start_line, chunk.end_line): chunk
            for chunk in file_chunks
            if chunk.symbol_name is not None
        }
        module = next((c for c in file_chunks if c.chunk_type == "module" and c.content), None)
        lines = tuple(module.content.split("\n")) if module else ()
        if lines:
            modules[path] = lines

        statements, definitions, scope_dependencies, scope_parents = [], {}, {}, {}
        class_nodes, class_bindings, definition_scopes = {}, {}, {}
        try:
            tree = ast.parse(module.content) if module else None
            root_scope = symtable.symtable(module.content, "<context>", "exec") if module else None
            if tree is not None:
                statements = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                        # parser 的符号末尾可包含注释；AST 用同文件定义起点关联。
                        definitions[(node.name, start)] = node
                        if isinstance(node, ast.ClassDef):
                            class_nodes[(node.name, node.lineno)] = node

                def index_scope(scope, parent=None):
                    key = (scope.get_name(), scope.get_lineno())
                    scope_parents[scope] = parent
                    dependencies = {s.get_name() for s in scope.get_symbols() if s.is_referenced() and s.is_global()}
                    if scope.get_type() == "class" and key in class_nodes:
                        outer = parent
                        while outer is not None and outer.get_type() == "class":
                            outer = scope_parents[outer]
                        class_dependencies, class_bindings[scope] = _class_reads(class_nodes[key], scope, outer or parent)
                        dependencies.update(class_dependencies)
                    for child in scope.get_children():
                        dependencies.update(index_scope(child, scope))
                    scope_dependencies[scope] = dependencies
                    # 匿名推导式可能与真正定义同名同行；父定义在子作用域后登记。
                    definition_scopes[(scope.get_type(), scope.get_name(), scope.get_lineno())] = scope
                    return dependencies

                index_scope(root_scope)
        except (SyntaxError, ValueError, RecursionError):
            statements = []

        symbol_fragments, references_by_fragment = [], {}
        for symbol in file_symbols:
            name = symbol.qualified_name or symbol.name
            score = sum(term in f"{path} {name}".lower() for term in terms)
            chunk = chunks_by_range.get((name, symbol.start_line, symbol.end_line))
            body = lines[symbol.start_line - 1:symbol.end_line] if lines else tuple(
                (chunk.content if chunk else symbol.signature or name).splitlines()
            )
            fragment = Fragment(
                path,
                f"符号: {name}",
                symbol.start_line,
                body,
                (0 if score else 3, -score, len(body), path, symbol.start_line),
                True,
            )
            symbol_fragments.append(fragment)
            definition = definitions.get((symbol.name, symbol.start_line))
            if definition is None:
                dependencies = _names("\n".join(body))
            else:
                scope_key = (definition.name, definition.lineno)
                scope_type = "class" if isinstance(definition, ast.ClassDef) else "function"
                original_scope = definition_scopes.get((scope_type, definition.name, definition.lineno))
                dependencies = set(scope_dependencies.get(original_scope, ()))
                parent = scope_parents.get(original_scope)
                if parent is not None:
                    bound = class_bindings.get(parent, {}).get(scope_key, ())
                    outer = parent
                    while outer is not None and outer.get_type() == "class":
                        outer = scope_parents.get(outer)
                    for head in _definition_heads(definition):
                        direct, nested = _expression_reads(head)
                        dependencies.update(
                            name for name in direct
                            if _is_module_read(parent, name, bound)
                        )
                        dependencies.update(
                            name for name in nested
                            if outer is not None and _is_module_read(outer, name)
                        )
            references_by_fragment[fragment] = dependencies

        fragments.extend(symbol_fragments)
        relevant = [f for f in symbol_fragments if f.priority[0] == 0] or symbol_fragments
        references = set().union(*(references_by_fragment[f] for f in relevant)) if relevant else set()
        selected_names = {f.label.removeprefix("符号: ").split(".")[-1] for f in relevant}
        if not module:
            if not symbol_fragments:
                for chunk in file_chunks:
                    fragments.append(Fragment(path, "已有代码块", chunk.start_line, tuple(chunk.content.splitlines()), (4, 0, 0, path, chunk.start_line)))
            continue
        if not statements and not symbol_fragments:
            fragments.append(Fragment(path, "模块", 1, lines, (4, 0, 0, path, 1)))

        bindings_by_name, unbound_by_name, loaded_by_statement = defaultdict(list), defaultdict(list), {}
        needed = set()
        for index, node in enumerate(statements):
            code = "\n".join(lines[node.lineno - 1:node.end_lineno])
            try:
                statement_scope = symtable.symtable(code, "<context>", "exec")
                bindings = {s.get_name() for s in statement_scope.get_symbols() if s.is_assigned() or s.is_imported()}
                loaded = _names("", scope=statement_scope)
            except (SyntaxError, ValueError, RecursionError):
                bindings, loaded = set(), _names(code)
            loaded_by_statement[index] = loaded
            for name in bindings:
                bindings_by_name[name].append(index)
            if not bindings:
                for name in loaded:
                    unbound_by_name[name].append(index)
            if loaded & selected_names or "__name__" in loaded or {name.lower() for name in bindings} & terms:
                needed.add(index)

        queue = deque(references)
        for index in needed:
            queue.extend(loaded_by_statement[index])
        seen_names = set()
        while queue:
            name = queue.popleft()
            if name in seen_names:
                continue
            seen_names.add(name)
            for index in bindings_by_name.get(name, []) + unbound_by_name.get(name, []):
                if index not in needed:
                    needed.add(index)
                    queue.extend(loaded_by_statement[index])
        for index, node in enumerate(statements):
            priority = 1 if index in needed else 2 if isinstance(node, (ast.Import, ast.ImportFrom)) else 4
            fragments.append(Fragment(path, "模块证据", node.lineno, lines[node.lineno - 1:node.end_lineno], (priority, 0, 0, path, node.lineno)))
    return sorted(fragments, key=lambda f: f.priority), modules


def _uncovered(fragment, covered):
    run, start = [], fragment.start
    for offset, line in enumerate(fragment.lines):
        number = fragment.start + offset
        if number in covered:
            if run:
                yield Fragment(fragment.path, fragment.label, start, tuple(run), fragment.priority, fragment.symbol)
                run = []
        else:
            if not run:
                start = number
            run.append(line)
    if run:
        yield Fragment(fragment.path, fragment.label, start, tuple(run), fragment.priority, fragment.symbol)


def build_code_context(source_files, symbols, chunks, prompt: str, budget: int) -> str:
    """优先完整相关符号和模块语句；超长目标按完整行保留首尾并披露缺口。"""
    budget = max(0, budget)
    fragments, modules = _fragments(source_files, symbols, chunks, prompt)
    reserve = len(OMISSION_NOTICE) + len(INCOMPLETE_NOTICE) + 4
    limit = max(0, budget - reserve)
    blocks, covered = [], {}
    used, omitted, incomplete = 0, False, False

    def add(fragment):
        nonlocal used
        text = fragment.render()
        size = len(text) + (2 if blocks else 0)
        if used + size > limit:
            return False
        blocks.append(text)
        used += size
        covered.setdefault(fragment.path, set()).update(range(fragment.start, fragment.start + len(fragment.lines)))
        return True

    for candidate in fragments:
        for fragment in _uncovered(candidate, covered.get(candidate.path, set())):
            if add(fragment):
                continue
            omitted = True
            if not fragment.symbol:
                continue
            incomplete = True
            # 为 imports/常量/入口预留空间，不让一个超长函数独占全部预算。
            allowance = min(limit - used - 2, int(limit * 0.6))
            for tail in (False, True):
                part, size = [], len(fragment.render().split("\n", 1)[0]) + 2
                ordered = list(reversed(fragment.lines)) if tail else fragment.lines
                for line in ordered:
                    if size + len(line) + 1 > allowance // 2:
                        break
                    part.append(line)
                    size += len(line) + 1
                if part:
                    start = fragment.start + len(fragment.lines) - len(part) if tail else fragment.start
                    add(Fragment(fragment.path, fragment.label, start, tuple(reversed(part)) if tail else tuple(part), fragment.priority, True))
            if not any(number in covered.get(fragment.path, set()) for number in range(fragment.start, fragment.start + len(fragment.lines))):
                end = fragment.start + len(fragment.lines) - 1
                notice = f"# [证据不足：{fragment.path} 行 {fragment.start}-{end} {fragment.label} 过长，源码已省略]"
                size = len(notice) + (2 if blocks else 0)
                if used + size <= limit:
                    blocks.append(notice)
                    used += size
    for path, lines in modules.items():
        if any(line.strip() and index not in covered.get(path, set()) for index, line in enumerate(lines, 1)):
            omitted = True
    if omitted:
        blocks.append(OMISSION_NOTICE)
    if incomplete:
        blocks.append(INCOMPLETE_NOTICE)
    text = "\n\n".join(blocks)
    if not text:
        text = "没有可用代码片段；证据不足，请勿推断业务关系。"
    # 极小预算只返回说明，不截断源码字符串。
    return text if len(text) <= budget else "证据不足；上下文预算过小。"[:budget]

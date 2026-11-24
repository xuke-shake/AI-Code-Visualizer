"""控制流图（CFG）构建：明确分支、返回与异常路径。

基于 Python 标准库 ast 构建语句级 CFG，并为每个函数/方法建立独立的作用域子图：

- 作用域：module 用 "<module>"，函数/方法用点分限定名（"f"、"outer.inner"、"C.m"），
  每个作用域有 entry / exit 节点；return 指向所在作用域的 exit
- 分支：if/elif/else 产生 if 节点与 true/false 边；for/while 产生 for/while 节点、
  loop_exit 合并点与回边；match/case 产生 match 节点与 case 边
- 返回：return 节点 -> 所在作用域 exit（return 边）
- 异常：try 节点 -> 各 except 处理（exception 边）；raise -> 最近的 except 或所在作用域 exit
- 跳转：break -> loop_exit，continue -> 循环头

简化说明：finally 节点仅在正常路径上执行；return/raise 穿过 finally 的场景
（例如 return 前先执行 finally）未单独建模，v1 直接连向 exit / handler。
语法错误时 build_cfg 直接抛出 SyntaxError。
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.source_file import SourceFile

logger = logging.getLogger(__name__)


@dataclass
class CFGNode:
    id: int
    kind: str          # entry / exit / function / class / if / for / while / loop_exit / break /
                       # continue / return / raise / try / except / finally / match / case / stmt
    label: str         # 可读文本，如 "if x > 0" / "return x" / "except ValueError"
    start_line: int    # 1-based，含
    end_line: int      # 1-based，含
    function: str      # 所属作用域限定名："<module>" / "f" / "outer.inner" / "C.m"


@dataclass
class CFGEdge:
    source: int
    target: int
    kind: str          # next / enter / true / false / exception / return / raise / break / continue / case
    label: str = ""


@dataclass
class ControlFlowGraph:
    nodes: list[CFGNode] = field(default_factory=list)
    edges: list[CFGEdge] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化为字典，便于后续接入 API / 前端。"""
        return {
            "nodes": [
                {"id": n.id, "kind": n.kind, "label": n.label,
                 "start_line": n.start_line, "end_line": n.end_line, "function": n.function}
                for n in self.nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target, "kind": e.kind, "label": e.label}
                for e in self.edges
            ],
        }


@dataclass
class _Scope:
    """当前作用域：节点归属的限定名 + 返回出口。"""
    qualname: str
    exit_id: int | None


@dataclass
class _Ctx:
    """递归构建时的循环/异常上下文。"""
    break_id: int | None = None
    continue_id: int | None = None
    handlers: list[int] = field(default_factory=list)   # 最近 try 的 except 处理入口


class _CFGBuilder:
    def __init__(self, code: str):
        self.code = code
        self.nodes: list[CFGNode] = []
        self.edges: list[CFGEdge] = []
        self._next_id = 0

    def _node(self, kind: str, label: str, start_line: int, end_line: int, qualname: str) -> int:
        node = CFGNode(self._next_id, kind, label, start_line, end_line, qualname)
        self.nodes.append(node)
        self._next_id += 1
        return node.id

    def _edge(self, src: int, dst: int, kind: str, label: str = "") -> None:
        self.edges.append(CFGEdge(src, dst, kind, label))

    def _label(self, node) -> str:
        """取节点对应源码文本并折叠为单行。"""
        try:
            seg = ast.get_source_segment(self.code, node)
        except (ValueError, AttributeError):
            seg = None
        return " ".join(seg.split()) if seg else ""

    def _stmt_list(self, stmts, next_id: int | None, scope: _Scope, ctx: _Ctx) -> int | None:
        """按顺序构建语句列表，返回入口节点 id；空列表返回 next_id。"""
        entry = next_id
        for stmt in reversed(stmts):
            entry = self._stmt(stmt, entry, scope, ctx)
        return entry

    def _stmt(self, node, next_id: int | None, scope: _Scope, ctx: _Ctx) -> int:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._function(node, next_id, scope, ctx)
        if isinstance(node, ast.ClassDef):
            return self._class(node, next_id, scope, ctx)
        if isinstance(node, ast.If):
            return self._if(node, next_id, scope, ctx)
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            return self._loop(node, next_id, scope, ctx)
        if isinstance(node, ast.Try):
            return self._try(node, next_id, scope, ctx)
        if isinstance(node, ast.Match):
            return self._match(node, next_id, scope, ctx)
        if isinstance(node, ast.Break):
            return self._break(node, scope, ctx)
        if isinstance(node, ast.Continue):
            return self._continue(node, scope, ctx)
        if isinstance(node, ast.Return):
            return self._return(node, scope)
        if isinstance(node, ast.Raise):
            return self._raise(node, scope, ctx)
        return self._plain(node, next_id, scope)

    def _plain(self, node, next_id: int, scope: _Scope) -> int:
        nid = self._node("stmt", self._label(node) or node.__class__.__name__,
                         node.lineno, getattr(node, "end_lineno", node.lineno), scope.qualname)
        self._edge(nid, next_id, "next")
        return nid

    def _if(self, node, next_id: int, scope: _Scope, ctx: _Ctx) -> int:
        cond = self._node("if", "if " + self._label(node.test), node.lineno, node.end_lineno, scope.qualname)
        then_entry = self._stmt_list(node.body, next_id, scope, ctx)
        else_entry = self._stmt_list(node.orelse, next_id, scope, ctx)
        self._edge(cond, then_entry, "true")
        self._edge(cond, else_entry, "false")
        return cond

    def _loop_label(self, node) -> str:
        if isinstance(node, ast.While):
            return "while " + self._label(node.test)
        prefix = "async for " if isinstance(node, ast.AsyncFor) else "for "
        return f"{prefix}{self._label(node.target)} in {self._label(node.iter)}"

    def _loop(self, node, next_id: int, scope: _Scope, ctx: _Ctx) -> int:
        kind = "for" if isinstance(node, (ast.For, ast.AsyncFor)) else "while"
        header = self._node(kind, self._loop_label(node), node.lineno, node.end_lineno, scope.qualname)
        loop_exit = self._node("loop_exit", "loop exit", node.end_lineno, node.end_lineno, scope.qualname)
        # 循环体正常结束回到 header；break 到 loop_exit；continue 到 header
        loop_ctx = _Ctx(break_id=loop_exit, continue_id=header, handlers=ctx.handlers)
        body_entry = self._stmt_list(node.body, header, scope, loop_ctx)
        # else 体（无 break 时）走 loop_exit 汇合
        else_entry = self._stmt_list(node.orelse, loop_exit, scope, ctx)
        self._edge(header, body_entry, "true")
        self._edge(header, else_entry, "false")
        self._edge(loop_exit, next_id, "next")
        return header

    def _try(self, node, next_id: int, scope: _Scope, ctx: _Ctx) -> int:
        try_nid = self._node("try", "try", node.lineno, node.end_lineno, scope.qualname)

        handler_ids = []
        for h in node.handlers:
            label = "except " + self._label(h.type) if h.type is not None else "except"
            handler_ids.append(self._node("except", label, h.lineno, getattr(h, "end_lineno", h.lineno), scope.qualname))

        final_id = None
        if node.finalbody:
            final_id = self._node("finally", "finally",
                                  node.finalbody[0].lineno, node.finalbody[-1].end_lineno, scope.qualname)

        join_id = final_id if final_id is not None else next_id
        # try 体内 raise 走本 try 的 handler；handler 体内 raise（re-raise）走外层 handler
        body_ctx = _Ctx(break_id=ctx.break_id, continue_id=ctx.continue_id,
                        handlers=handler_ids or ctx.handlers)
        handler_ctx = _Ctx(break_id=ctx.break_id, continue_id=ctx.continue_id,
                           handlers=ctx.handlers)

        else_entry = join_id
        if node.orelse:
            else_entry = self._stmt_list(node.orelse, join_id, scope, body_ctx)

        body_entry = self._stmt_list(node.body, else_entry, scope, body_ctx)
        self._edge(try_nid, body_entry, "next")

        for hid, h in zip(handler_ids, node.handlers):
            self._edge(try_nid, hid, "exception")
            handler_body_entry = self._stmt_list(h.body, join_id, scope, handler_ctx)
            self._edge(hid, handler_body_entry, "next")

        if final_id is not None:
            final_body_entry = self._stmt_list(node.finalbody, next_id, scope, ctx)
            self._edge(final_id, final_body_entry, "next")

        return try_nid

    def _case_label(self, case) -> str:
        return "case " + self._label(case.pattern)

    def _match(self, node, next_id: int, scope: _Scope, ctx: _Ctx) -> int:
        m = self._node("match", "match " + self._label(node.subject), node.lineno, node.end_lineno, scope.qualname)
        for case in node.cases:
            start = case.pattern.lineno
            end = case.body[-1].end_lineno if case.body else getattr(case.pattern, "end_lineno", start)
            c = self._node("case", self._case_label(case), start, end, scope.qualname)
            body_entry = self._stmt_list(case.body, next_id, scope, ctx)
            self._edge(m, c, "case")
            self._edge(c, body_entry, "next")
        return m

    def _function(self, node, next_id: int, scope: _Scope, ctx: _Ctx, class_qual: str | None = None) -> int:
        parent_qual = scope.qualname
        name = node.name
        if class_qual is not None:
            qual = f"{class_qual}.{name}"
        else:
            qual = name if parent_qual == "<module>" else f"{parent_qual}.{name}"
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        label = f"{prefix} {name}({self._label(node.args)})"

        # def 语句本身是父作用域中的一个节点
        fn = self._node("function", label, node.lineno, node.end_lineno, parent_qual)
        fn_entry = self._node("entry", "entry", node.lineno, node.lineno, qual)
        fn_exit = self._node("exit", "exit", node.end_lineno, node.end_lineno, qual)
        body_entry = self._stmt_list(node.body, fn_exit, _Scope(qual, fn_exit), _Ctx())

        self._edge(fn_entry, body_entry, "next")
        self._edge(fn, fn_entry, "enter")
        self._edge(fn, next_id, "next")   # def 语句在父作用域继续向下
        return fn

    def _class(self, node, next_id: int, scope: _Scope, ctx: _Ctx) -> int:
        parent_qual = scope.qualname
        name = node.name
        class_qual = name if parent_qual == "<module>" else f"{parent_qual}.{name}"
        cls = self._node("class", f"class {name}", node.lineno, node.end_lineno, parent_qual)

        # 方法各自成作用域；类级其它语句在父作用域内执行
        entry = next_id
        for stmt in reversed(node.body):
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                entry = self._function(stmt, entry, scope, ctx, class_qual=class_qual)
            else:
                entry = self._stmt(stmt, entry, scope, ctx)
        self._edge(cls, entry, "next")
        return cls

    def _break(self, node, scope: _Scope, ctx: _Ctx) -> int:
        nid = self._node("break", "break", node.lineno, node.end_lineno, scope.qualname)
        self._edge(nid, ctx.break_id if ctx.break_id is not None else scope.exit_id, "break")
        return nid

    def _continue(self, node, scope: _Scope, ctx: _Ctx) -> int:
        nid = self._node("continue", "continue", node.lineno, node.end_lineno, scope.qualname)
        if ctx.continue_id is not None:
            self._edge(nid, ctx.continue_id, "continue")
        return nid

    def _return(self, node, scope: _Scope) -> int:
        nid = self._node("return", self._label(node) or "return", node.lineno, node.end_lineno, scope.qualname)
        self._edge(nid, scope.exit_id, "return")
        return nid

    def _raise(self, node, scope: _Scope, ctx: _Ctx) -> int:
        nid = self._node("raise", self._label(node) or "raise", node.lineno, node.end_lineno, scope.qualname)
        if ctx.handlers:
            for hid in ctx.handlers:
                self._edge(nid, hid, "exception")
        else:
            self._edge(nid, scope.exit_id, "exception")
        return nid


def build_cfg(code: str) -> ControlFlowGraph:
    """解析一段 Python 源码，构建控制流图。语法错误时抛出 SyntaxError。"""
    tree = ast.parse(code)

    builder = _CFGBuilder(code)
    entry = builder._node("entry", "entry", 1, 1, "<module>")

    exit_id = None
    if tree.body:
        last_line = max(1, len(code.splitlines()))
        exit_id = builder._node("exit", "exit", last_line, last_line, "<module>")

    body_entry = builder._stmt_list(tree.body, exit_id, _Scope("<module>", exit_id), _Ctx())
    if body_entry is not None:
        builder._edge(entry, body_entry, "next")

    return ControlFlowGraph(nodes=builder.nodes, edges=builder.edges)


def save_control_flow(db: Session, source_file_id: int, code: str) -> str | None:
    """构建控制流图并写入 SourceFile.control_flow；失败时记录原因、保留旧结果。

    - 成功：保存新 CFG（含内容版本 file_hash），清除 control_flow_error。
    - Python 语法错误 / CFG 算法异常：不覆盖旧 control_flow，把失败原因写入
      control_flow_error。返回错误文本（成功返回 None）。
    """
    source_file = db.get(SourceFile, source_file_id)
    if source_file is None:
        return None
    try:
        cfg = build_cfg(code)
    except SyntaxError as exc:
        error = f"Python 语法错误：{exc}"
        source_file.control_flow_error = error
        logger.warning("CFG 构建跳过（语法错误）source_file_id=%s：%s", source_file_id, exc)
        return error
    except Exception as exc:
        error = f"CFG 构建异常：{exc}"
        source_file.control_flow_error = error
        logger.exception("CFG 构建异常 source_file_id=%s", source_file_id, exc_info=exc)
        return error
    source_file.control_flow = {"version": source_file.file_hash, **cfg.to_dict()}
    source_file.control_flow_error = None
    return None

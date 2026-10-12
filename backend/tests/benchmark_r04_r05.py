"""算法微基准；不含数据库查询、HTTP、模型或端到端延迟。

backend 目录运行：py -3.11 -X utf8 tests/benchmark_r04_r05.py
使用实际 ORM 类型和 parser，scalars 返回预加载对象；不连接开发库。
"""
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "benchmark-local-only"
os.environ["LLM_ENABLED"] = "off"


def measure(callback, repeat=3):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        result = callback()
        samples.append(time.perf_counter() - start)
        assert result
    return {"seconds": samples, "median_seconds": statistics.median(samples)}


def main():
    with tempfile.TemporaryDirectory(prefix="r04-r05-benchmark-") as storage:
        os.environ["STORAGE_DIR"] = storage
        from app.agents.context_builder import build_code_context
        from app.models.code_chunk import CodeChunk
        from app.models.source_file import SourceFile
        from app.models.symbol import Symbol
        from app.parsing.tree_parser import parse_source
        from app.services.index_service import IndexService

        chain = "\n".join(["A0 = 1"] + [f"A{i} = A{i-1}" for i in range(1, 1001)] + ["def target():", "    return A1000"])
        sf = SimpleNamespace(id=1, relative_path="chain.py")
        symbol = SimpleNamespace(file_id=1, qualified_name=None, name="target", start_line=1002, end_line=1003, signature=None)
        module = SimpleNamespace(file_id=1, chunk_type="module", symbol_name=None, content=chain)
        context = measure(lambda: build_code_context([sf], [symbol], [module], "target", 12000))

        code = "\n".join(f"def f{i}():\n    return {i}" for i in range(4000))
        lines = code.splitlines()
        parsed = parse_source(code)
        assert len(parsed) == 4000
        file = SourceFile(id=1, project_id=1, relative_path="many.py", language="python", parse_status="parsed", file_hash="same", line_count=len(lines))
        symbols = [Symbol(file_id=1, name=s.name, kind=s.kind, qualified_name=s.qualified_name,
                          start_line=s.start_line, end_line=s.end_line) for s in parsed]
        chunks = [CodeChunk(file_id=1, chunk_type="module", start_line=1, end_line=len(lines), content="\n".join(lines))]
        chunks.extend(CodeChunk(file_id=1, chunk_type=s.kind, symbol_name=s.qualified_name or s.name,
                                start_line=s.start_line, end_line=s.end_line,
                                content="\n".join(lines[s.start_line - 1:s.end_line])) for s in parsed)

        class LoadedRows:
            def scalars(self, query):
                model = query.column_descriptions[0]["entity"]
                return SimpleNamespace(all=lambda: chunks if model is CodeChunk else symbols)

        project = SimpleNamespace(id=1, status="ready", source_type="zip", last_index_version="upload:1:v3:benchmark",
                                  repository=SimpleNamespace(upload_id=1))
        service = IndexService(LoadedRows())
        contract = measure(lambda: service._has_current_chunk_contract(project, {"many.py": {"content": code, "hash": "same"}}, {"many.py": file}))
        print(json.dumps({"context": {"chain_depth": 1000, "source_chars": len(chain), **context},
                          "contract": {"functions": 4000, "source_chars": len(code), **contract}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

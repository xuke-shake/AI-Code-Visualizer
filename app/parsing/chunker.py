from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.parsing.tree_parser import SymbolInfo
from app.tools.hash_utils import sha256_text


def chunk_and_save(
    db: Session,
    project_id: int,
    source_file_id: int,
    code: str,
    symbols: list[SymbolInfo],
) -> list[int]:
    """按符号边界切分源码，写入code_chunks表，返回chunk ID列表。"""
    lines = code.splitlines()
    ids: list[int] = []

    for s in symbols:
        # 源码行号转0-based索引
        start = s.start_line - 1
        end = s.end_line  # end_line是包含的，slice取到end即可
        chunk_lines = lines[start:end]
        content = "\n".join(chunk_lines)

        chunk = CodeChunk(
            project_id=project_id,
            file_id=source_file_id,
            chunk_type=s.kind,
            symbol_name= s.qualified_name or s.name,
            start_line=s.start_line,
            end_line=s.end_line,
            content=content,
            content_hash=sha256_text(content),
        )
        db.add(chunk)
        db.flush()
        ids.append(chunk.id)

    return ids

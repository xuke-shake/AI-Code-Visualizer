from sqlalchemy.orm import Session

from app.models.symbol import Symbol
from app.parsing.tree_parser import SymbolInfo


def extract_and_save(
    db: Session, project_id: int, source_file_id: int, symbols: list[SymbolInfo]
) -> list[int]:
    """将已解析的符号列表写入symbols表，返回symbol ID列表。"""
    ids: list[int] = []

    for s in symbols:
        sym = Symbol(
            project_id=project_id,
            file_id=source_file_id,
            name=s.name,
            kind=s.kind,
            qualified_name=s.qualified_name,
            start_line=s.start_line,
            end_line=s.end_line,
            signature=s.signature,
        )
        db.add(sym)
        db.flush()
        ids.append(sym.id)

    return ids

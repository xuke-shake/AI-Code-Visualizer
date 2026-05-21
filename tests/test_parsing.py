"""测试 IndexService —— 模拟前端触发完整解析流程"""

from datetime import datetime, timezone
from pathlib import Path

from app.core.database import SessionLocal
from app.models.user import User
from app.models.project import Project
from app.models.repository import Repository
from app.models.analysis_task import AnalysisTask
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.code_chunk import CodeChunk
from app.models.dependency import Dependency
from app.services.index_service import IndexService

# ---- 配置 ----
ZIP_PATH = Path(r"D:\Program\Progrom_code\ai-code-visualizer-backend\storage\vue3.zip")
ZIP_OBJECT_KEY = "vue3.zip"  # 直接放在 storage 根目录
PROJECT_ID = 1
USER_ID = 1

db = SessionLocal()

# 1. 清理旧数据
print("清理旧数据...")
db.query(Dependency).delete()
db.query(CodeChunk).delete()
db.query(Symbol).delete()
db.query(SourceFile).delete()
db.query(AnalysisTask).delete()
db.query(Repository).delete()
db.query(Project).delete()
db.query(User).delete()
db.commit()
print("已清理\n")

# 2. 创建测试数据
now = datetime.now(timezone.utc)

user = User(id=USER_ID, email="test@test.com", password_hash="fake", role="user", status="normal", created_at=now)
db.add(user)
db.flush()

project = Project(id=PROJECT_ID, owner_id=USER_ID, name="test-project", source_type="zip", status="created", created_at=now, updated_at=now)
db.add(project)
db.flush()

repo = Repository(project_id=PROJECT_ID, zip_object_key=ZIP_OBJECT_KEY, created_at=now)
db.add(repo)
db.flush()

task = AnalysisTask(
    project_id=PROJECT_ID,
    user_id=USER_ID,
    task_type="parse",
    status="pending",
    progress=0,
    created_at=now,
)
db.add(task)
db.flush()
db.commit()
print(f"已创建: User={user.id}, Project={project.id}, Repository={repo.id}, AnalysisTask={task.id}\n")

# 3. 调用 IndexService
print("=" * 60)
print("IndexService.parse_full 开始")
print("=" * 60)
task = IndexService(db).parse_full(project, task)
db.commit()
print(f"\ntask.status:  {task.status}")
print(f"task.message: {task.message}")
print(f"task.result_json: {task.result_json}\n")

# 4. 验证数据库
print("=" * 60)
print("数据库验证")
print("=" * 60)
print(f"source_files: {db.query(SourceFile).count()}")
print(f"symbols:      {db.query(Symbol).count()}")
print(f"code_chunks:  {db.query(CodeChunk).count()}")
print(f"dependencies: {db.query(Dependency).count()}")

print("\n(symbols 前20条)")
for s in db.query(Symbol).limit(20).all():
    print(f"  [{s.kind:<10}] {s.qualified_name or s.name:<35} lines={s.start_line}-{s.end_line}")

print("\n(code_chunks 前20条)")
for c in db.query(CodeChunk).limit(20).all():
    print(f"  [{c.chunk_type:<10}] {c.symbol_name:<35} lines={c.start_line}-{c.end_line}  hash={c.content_hash}")

print("\n(dependencies 前20条)")
for d in db.query(Dependency).limit(20).all():
    src = db.query(SourceFile).get(d.source_file_id) if d.source_file_id else None
    tgt = db.query(SourceFile).get(d.target_file_id) if d.target_file_id else None
    src_path = Path(src.relative_path).name if src else "?"
    tgt_path = Path(tgt.relative_path).name if tgt else "?"
    print(f"  {d.relation_type}: {src_path} -> {tgt_path}  (confidence={d.confidence})  evidence: {d.evidence}")

# 5. 测试 sync_incremental —— 同一 ZIP 再次同步，应检测到无变化
print("\n" + "=" * 60)
print("sync_incremental 开始 (同 ZIP)")
print("=" * 60)

sync_task = AnalysisTask(
    project_id=PROJECT_ID,
    user_id=USER_ID,
    task_type="sync",
    status="pending",
    progress=0,
    created_at=datetime.now(timezone.utc),
)
db.add(sync_task)
db.flush()

sync_task = IndexService(db).sync_incremental(project, sync_task)
db.commit()
print(f"status:        {sync_task.status}")
print(f"message:       {sync_task.message}")
print(f"result_json:   {sync_task.result_json}")

print("\n" + "=" * 60)
print("增量同步后数据")
print("=" * 60)
print(f"source_files: {db.query(SourceFile).count()}")
print(f"symbols:      {db.query(Symbol).count()}")
print(f"code_chunks:  {db.query(CodeChunk).count()}")
print(f"dependencies: {db.query(Dependency).count()}")

db.close()
print("\n完成")

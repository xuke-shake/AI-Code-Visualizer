from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.project import Project
from app.models.analysis_task import AnalysisTask


class IndexService:
    """源码解析服务占位实现。

    后续源码解析负责人可以在这里接入Tree-sitter、Chunking、Embedding和向量库。
    当前版本保证接口可联调：会写入任务结果并更新项目状态。
    """

    def __init__(self, db: Session):
        self.db = db

    def parse_full(self, project: Project, task: AnalysisTask) -> AnalysisTask:
        project.status = "parsing"
        task.status = "running"
        task.progress = 20
        task.message = "正在扫描文件"
        self.db.flush()

        # 占位结果。真实解析时由source_files/code_chunks/symbols/dependencies数量替换。
        project.status = "ready"
        project.file_count = project.file_count or 0
        project.last_index_version = f"idx-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        task.status = "success"
        task.progress = 100
        task.message = "解析完成，已建立基础索引"
        task.result_json = {
            "source_files": project.file_count,
            "code_chunks": 0,
            "symbols": 0,
            "dependencies": 0,
            "note": "当前为后端骨架占位结果，后续接入Tree-sitter后替换。",
        }
        task.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(task)
        return task

    def sync_incremental(self, project: Project, task: AnalysisTask) -> AnalysisTask:
        task.status = "success"
        task.progress = 100
        task.message = "同步完成"
        task.result_json = {"added": [], "modified": [], "deleted": [], "outdated_diagrams": 0}
        task.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(task)
        return task

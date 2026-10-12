from app.tasks.celery_app import celery_app


@celery_app.task(name="parse_project")
def parse_project_task(project_id: int, task_id: int) -> dict:
    # 后续接入IndexService.parse_full。当前返回占位结果，避免Worker导入失败。
    return {"project_id": project_id, "task_id": task_id, "status": "queued"}

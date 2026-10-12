"""Fresh head and existing rows upgrade without inventing historical usage."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


@pytest.mark.parametrize('existing', [False, True])
def test_usage_migration_preserves_old_data_and_marks_unknown(tmp_path, existing):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / 'migration.sqlite3'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{database.as_posix()}',
           'STORAGE_DIR': str(tmp_path / 'storage'), 'SECRET_KEY': 'migration-test', 'LLM_ENABLED': 'off'}
    def migrate(target):
        result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', target], cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
    if existing:
        migrate('20261003_0002')
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO users(id,email,password_hash,role,status,created_at) VALUES(1,'migration@example.com','unused','user','normal',CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO projects(id,owner_id,name,source_type,status,file_count,created_at,updated_at) VALUES(1,1,'migration','zip','created',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO analysis_tasks(id,project_id,user_id,task_type,status,progress,created_at) VALUES(1,1,1,'diagram','success',100,CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO agent_runs(id,task_id,agent_name,model_name,prompt_tokens,completion_tokens,latency_ms,status) VALUES(1,1,'DiagramAgent','historical',12,3,0,'success')")
    migrate('head')
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == ('20261011_0003',)
        assert 'usage_collected' in [row[1] for row in db.execute('PRAGMA table_info(agent_runs)')]
        if existing:
            assert db.execute('SELECT prompt_tokens,completion_tokens,usage_collected FROM agent_runs').fetchone() == (12, 3, 0)

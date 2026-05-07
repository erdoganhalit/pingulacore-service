from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.db.models import PipelineAgentLink


def test_sub_pipeline_writes_links(client) -> None:
    settings = get_settings()
    q_dir = settings.root_dir / "sp_files" / "q_json"
    q_dir.mkdir(parents=True, exist_ok=True)
    before_files = set(path.name for path in q_dir.iterdir() if path.is_file())

    payload = {"yaml_filename": "o08_iki_adimli_toplama.yaml"}
    resp = client.post("/v1/pipelines/sub/yaml-to-question/run", json=payload)
    assert resp.status_code == 200, resp.text

    data = resp.json()
    sub_id = data["sub_pipeline_id"]

    runs_resp = client.get(f"/v1/sub-pipelines/{sub_id}/agent-runs")
    assert runs_resp.status_code == 200
    runs = runs_resp.json()
    assert len(runs) >= 3

    with SessionLocal() as db:
        rows = list(db.scalars(select(PipelineAgentLink).where(PipelineAgentLink.sub_pipeline_id == sub_id)))
        assert rows
        assert any(row.agent_name == "main_generate_question" for row in rows)

    after_files = set(path.name for path in q_dir.iterdir() if path.is_file())
    new_files = after_files - before_files
    assert any(sub_id in name for name in new_files)

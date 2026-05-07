from __future__ import annotations

from sqlalchemy import select

from app.agents.agent_service import AgentService
from app.core.config import get_settings
from app.db.database import SessionLocal
from app.db.models import PipelineLog
from app.schemas.domain import HtmlValidationResult, QuestionLayoutValidationResult, RuleEvaluation, RuleEvaluationSet


def test_full_pipeline_and_get_endpoints(client) -> None:
    run_resp = client.post(
        "/v1/pipelines/full/run",
        json={
            "yaml_filename": "o08_iki_adimli_toplama.yaml",
            "retry_config": {"question_max_retries": 2, "layout_max_retries": 2, "html_max_retries": 2},
        },
    )
    assert run_resp.status_code == 200, run_resp.text

    body = run_resp.json()
    pipeline_id = body["pipeline_id"]
    sub_ids = body["sub_pipeline_ids"]

    p_resp = client.get(f"/v1/pipelines/{pipeline_id}")
    assert p_resp.status_code == 200
    assert p_resp.json()["status"] == "success"

    pa_resp = client.get(f"/v1/pipelines/{pipeline_id}/agent-runs")
    assert pa_resp.status_code == 200
    pa_runs = pa_resp.json()
    assert pa_runs

    pl_resp = client.get(f"/v1/pipelines/{pipeline_id}/logs")
    assert pl_resp.status_code == 200
    pl_rows = pl_resp.json()
    assert pl_rows
    assert any("pipeline" in (row.get("component") or "") for row in pl_rows)

    for _, sub_id in sub_ids.items():
        s_resp = client.get(f"/v1/sub-pipelines/{sub_id}")
        assert s_resp.status_code == 200
        sr_resp = client.get(f"/v1/sub-pipelines/{sub_id}/agent-runs")
        assert sr_resp.status_code == 200
        assert sr_resp.json()
        sl_resp = client.get(f"/v1/sub-pipelines/{sub_id}/logs")
        assert sl_resp.status_code == 200
        assert sl_resp.json()

    one_run = pa_runs[0]
    ar_resp = client.get(f"/v1/agent-runs/{one_run['agent_name']}/{one_run['agent_run_id']}")
    assert ar_resp.status_code == 200
    assert ar_resp.json()["id"] == one_run["agent_run_id"]


def test_standalone_endpoints(client) -> None:
    yaml_payload = {
        "yaml_content": {
            "meta": {"ad": "test"},
            "context": {"type": "test"},
            "format": {"options": {"labels": ["A", "B", "C"]}},
        }
    }
    q_resp = client.post("/v1/agents/main/generate-question/run", json=yaml_payload)
    assert q_resp.status_code == 200

    question_json = q_resp.json()["result"]
    l_resp = client.post("/v1/agents/main/generate-layout/run", json={"question_json": question_json})
    assert l_resp.status_code == 200

    layout_json = l_resp.json()["result"]
    h_resp = client.post(
        "/v1/agents/main/generate-html/run",
        json={"question_json": question_json, "layout_plan_json": layout_json},
    )
    assert h_resp.status_code == 200

    v_resp = client.post(
        "/v1/agents/validation/validate-layout-html/run",
        json={"layout_plan_json": layout_json, "html_content": h_resp.json()["result"]["html_content"]},
    )
    assert v_resp.status_code == 200

    with SessionLocal() as db:
        logs = list(db.scalars(select(PipelineLog).where(PipelineLog.mode == "standalone")))
        assert logs
        assert any((row.component or "").startswith("standalone.main_generate_question") for row in logs)


def test_full_pipeline_returns_last_html_and_render_when_html_validation_fails(client, monkeypatch) -> None:
    def _always_fail_validate_html(self, html_content: str, rendered_image_path: str) -> HtmlValidationResult:  # noqa: ANN001
        return HtmlValidationResult(
            overall_status="fail",
            issues=["forced-fail"],
            feedback="forced feedback",
        )

    monkeypatch.setattr(AgentService, "validate_html", _always_fail_validate_html)

    run_resp = client.post(
        "/v1/pipelines/full/run",
        json={
            "yaml_filename": "o08_iki_adimli_toplama.yaml",
            "retry_config": {"html_max_retries": 1},
        },
    )
    assert run_resp.status_code == 200, run_resp.text
    body = run_resp.json()
    assert body.get("rendered_image_path")

    pipeline_id = body["pipeline_id"]
    p_resp = client.get(f"/v1/pipelines/{pipeline_id}")
    assert p_resp.status_code == 200
    assert p_resp.json()["status"] == "success"

    sub_h_id = body["sub_pipeline_ids"]["layout_to_html"]
    sub_h_resp = client.get(f"/v1/sub-pipelines/{sub_h_id}")
    assert sub_h_resp.status_code == 200
    output = sub_h_resp.json()["output_json"]
    assert output["validation"]["overall_status"] == "fail"
    assert output.get("rendered_image_path")


def test_full_pipeline_saves_attempt_renders_final_render_and_normalized_html(client, monkeypatch) -> None:
    counter = {"attempt": 0}

    def _fail_once_then_pass(self, html_content: str, rendered_image_path: str) -> HtmlValidationResult:  # noqa: ANN001
        counter["attempt"] += 1
        if counter["attempt"] == 1:
            return HtmlValidationResult(
                overall_status="fail",
                issues=["forced-first-fail"],
                feedback="retry-once",
            )
        return HtmlValidationResult(
            overall_status="pass",
            issues=[],
            feedback="",
        )

    qhtml_before = client.get("/v1/sp-files/q_html").json()["files"]
    monkeypatch.setattr(AgentService, "validate_html", _fail_once_then_pass)

    run_resp = client.post(
        "/v1/pipelines/full/run",
        json={
            "yaml_filename": "o08_iki_adimli_toplama.yaml",
            "retry_config": {"html_max_retries": 2},
        },
    )
    assert run_resp.status_code == 200, run_resp.text
    body = run_resp.json()
    assert counter["attempt"] == 2
    assert body["rendered_image_path"].endswith("/render_final.png")

    run_dir = get_settings().root_dir / body["run_path"]
    assert (run_dir / "render_1.png").exists()
    assert (run_dir / "render_2.png").exists()
    assert (run_dir / "render_final.png").exists()
    assert not (run_dir / "render.png").exists()

    run_html = (run_dir / "question.html").read_text(encoding="utf-8")
    assert '/v1/assets/' in run_html
    assert 'src="catalog/' not in run_html
    assert "src=\"runs/" not in run_html

    assert '/v1/assets/' in body["question_html"]["html_content"]

    qhtml_after = client.get("/v1/sp-files/q_html").json()["files"]
    new_files = [name for name in qhtml_after if name not in qhtml_before]
    assert new_files
    latest_file = sorted(new_files)[-1]
    saved_html_resp = client.get(f"/v1/sp-files/q_html/{latest_file}")
    assert saved_html_resp.status_code == 200
    saved_html = saved_html_resp.json()["html_content"]
    assert '/v1/assets/' in saved_html


def test_sub_yaml_to_question_returns_last_question_when_rules_keep_failing(client, monkeypatch) -> None:
    async def _always_fail_rules(self, rules, question, parallelism=4, on_progress=None):  # noqa: ANN001
        items = [
            RuleEvaluation(
                rule_id=rule.id,
                category=rule.category,
                rule_text=rule.text,
                status="fail",
                rationale="forced fail for retry-exhaust test",
                confidence=0.8,
                evidence="",
            )
            for rule in rules
        ]
        if on_progress:
            for idx, item in enumerate(items, start=1):
                on_progress(idx, len(items), item)
        return RuleEvaluationSet(items=items)

    monkeypatch.setattr(AgentService, "evaluate_rules_parallel", _always_fail_rules)

    run_resp = client.post(
        "/v1/pipelines/sub/yaml-to-question/run",
        json={
            "yaml_filename": "o08_iki_adimli_toplama.yaml",
            "retry_config": {"question_max_retries": 2},
        },
    )
    assert run_resp.status_code == 200, run_resp.text
    body = run_resp.json()
    assert body["attempts"] == 2
    assert body["question_json"]["question_id"]
    assert body["rule_evaluation"]["items"]
    assert all(item["status"] == "fail" for item in body["rule_evaluation"]["items"])

    sub_id = body["sub_pipeline_id"]
    sub_resp = client.get(f"/v1/sub-pipelines/{sub_id}")
    assert sub_resp.status_code == 200
    sub_payload = sub_resp.json()["output_json"]
    assert sub_payload["question"]["question_id"]
    assert sub_payload["attempts"] == 2
    assert sub_payload["rule_evaluation"]["items"]


def test_sub_question_to_layout_returns_last_layout_when_validation_keeps_failing(client, monkeypatch) -> None:
    def _always_fail_layout_validation(self, question, layout):  # noqa: ANN001
        return QuestionLayoutValidationResult(
            overall_status="fail",
            issues=["forced layout validation fail"],
            feedback="retry but never pass",
        )

    monkeypatch.setattr(AgentService, "validate_question_layout", _always_fail_layout_validation)

    q_resp = client.post(
        "/v1/agents/main/generate-question/run",
        json={
            "yaml_content": {
                "meta": {"ad": "test"},
                "context": {"type": "test"},
                "format": {"options": {"labels": ["A", "B", "C"]}},
            }
        },
    )
    assert q_resp.status_code == 200, q_resp.text
    question_json = q_resp.json()["result"]

    run_resp = client.post(
        "/v1/pipelines/sub/question-to-layout/run",
        json={
            "question_json": question_json,
            "retry_config": {"layout_max_retries": 2},
        },
    )
    assert run_resp.status_code == 200, run_resp.text
    body = run_resp.json()
    assert body["attempts"] == 2
    assert body["layout_plan_json"]["asset_library"]
    assert body["validation"]["overall_status"] == "fail"
    assert body["validation"]["issues"]

    sub_id = body["sub_pipeline_id"]
    sub_resp = client.get(f"/v1/sub-pipelines/{sub_id}")
    assert sub_resp.status_code == 200
    sub_payload = sub_resp.json()["output_json"]
    assert sub_payload["layout"]["asset_library"]
    assert sub_payload["attempts"] == 2
    assert sub_payload["validation"]["overall_status"] == "fail"

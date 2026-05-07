from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from app.agents.agent_service import AgentService
from app.core.config import get_settings
from app.schemas.domain import GeneratedHtml
from app.schemas.domain import (
    AssetSpec,
    AssetType,
    EntitySpec,
    QuestionOptionSpec,
    QuestionScenarioSpec,
    QuestionSceneSpec,
    QuestionSpec,
    ValidationRule,
)


def _build_question() -> QuestionSpec:
    return QuestionSpec(
        question_id="q-1",
        scenario=QuestionScenarioSpec(
            entities=[EntitySpec(name="elma", description="meyve", quantity=3)],
            scenes=[QuestionSceneSpec(enabled=True, description_prompt="simple classroom scene", color_scheme="pastel")],
            characters=[],
            story="Kısa bir hikaye.",
        ),
        options=[
            QuestionOptionSpec(label="A", modality="text", is_correct=True, content="12"),
            QuestionOptionSpec(label="B", modality="visual", is_correct=False, content=[EntitySpec(name="elma", description="meyve", quantity=10)]),
            QuestionOptionSpec(label="C", modality="text", is_correct=False, content="14"),
        ],
        solution=["A doğru."],
        stem="Doğru cevabı seçiniz.",
        grade=2,
        difficulty="medium",
    )


def test_parallel_rule_evaluation_sorted_and_complete() -> None:
    agents = AgentService()
    question = _build_question()

    rules = [
        ValidationRule(id="R03", category="format", text="kural3"),
        ValidationRule(id="R01", category="format", text="kural1"),
        ValidationRule(id="R02", category="format", text="kural2"),
    ]

    result = asyncio.run(agents.evaluate_rules_parallel(rules, question, parallelism=2))
    assert [item.rule_id for item in result.items] == ["R01", "R02", "R03"]


def test_layout_html_validator_feedback_when_missing_asset() -> None:
    agents = AgentService()
    question = _build_question()
    layout = agents._stub_generate_layout(question)
    invalid_html = "<html><body>no-assets</body></html>"
    rendered = agents.render_html_to_image(invalid_html, asset_map={}, question_id=layout.question_id)
    validation = agents.validate_html(invalid_html, rendered)
    assert validation.overall_status == "fail"
    assert validation.feedback


def test_post_process_html_asset_paths_adds_catalog_and_generated_prefixes() -> None:
    agents = AgentService()
    question = _build_question()
    layout = agents._stub_generate_layout(question)
    layout.asset_library["catalog_student"] = AssetSpec(
        slug="catalog_student",
        asset_type=AssetType.CATALOG_COMPONENT,
        description="catalog student",
        source_filename="erkek_cocuk1.png",
        output_filename="erkek_cocuk1.png",
        kind="object",
        transparent_background=True,
        render_shape="free",
    )

    html = '<img src="erkek_cocuk1.png" /><img src="scenario_scene.png" />'
    processed = agents.post_process_html_asset_paths(
        html,
        layout,
        {"catalog_student": "erkek_cocuk1.png", "scenario_scene": "scenario_scene.png"},
    )
    assert 'src="catalog/erkek_cocuk1.png"' in processed
    assert 'src="generated_assets/scenario_scene.png"' in processed


def test_render_html_to_image_uses_attempt_suffix_in_run_dir(tmp_path: Path) -> None:
    agents = AgentService()
    html = "<html><body>render-attempt-test</body></html>"

    rendered_1 = agents.render_html_to_image(html, asset_map={}, render_dir=tmp_path, attempt=1)
    rendered_2 = agents.render_html_to_image(html, asset_map={}, render_dir=tmp_path, attempt=2)

    assert Path(rendered_1).name == "render_1.png"
    assert Path(rendered_2).name == "render_2.png"
    assert (tmp_path / "render_1.html").exists()
    assert (tmp_path / "render_2.html").exists()
    assert not (tmp_path / "render.png").exists()
    assert "file://" not in (tmp_path / "render_1.html").read_text(encoding="utf-8")
    assert "file://" not in (tmp_path / "render_2.html").read_text(encoding="utf-8")


def test_render_html_artifact_keeps_relative_paths_not_absolute_file_uris(tmp_path: Path) -> None:
    agents = AgentService()
    html = '<html><body><img src="catalog/erkek_cocuk1.png" alt="Ali"></body></html>'

    agents.render_html_to_image(html, asset_map={}, render_dir=tmp_path, attempt=1)
    persisted_html = (tmp_path / "render_1.html").read_text(encoding="utf-8")

    assert 'src="catalog/erkek_cocuk1.png"' in persisted_html
    assert "file:///Users/" not in persisted_html
    assert "file://" not in persisted_html
    assert not (tmp_path / "render_1.capture.html").exists()


def test_normalize_html_asset_urls_for_server_handles_runs_and_catalog() -> None:
    html = (
        '<img src="runs/full/run_1/render_1.png" />'
        '<img src="catalog/erkek_cocuk1.png" />'
        '<img src="kiz_cocuk1.png" />'
        "<style>.scene{background-image:url('runs/full/run_1/assets/classroom_scene.png')}</style>"
    )
    normalized = AgentService.normalize_html_asset_urls_for_server(html)
    assert 'src="/v1/assets/runs/full/run_1/render_1.png"' in normalized
    assert 'src="/v1/assets/erkek_cocuk1.png"' in normalized
    assert 'src="/v1/assets/kiz_cocuk1.png"' in normalized
    assert "background-image:url('/v1/assets/runs/full/run_1/assets/classroom_scene.png')" in normalized


def test_local_render_rewrite_handles_css_background_runs_path() -> None:
    settings = get_settings()
    agents = AgentService()
    run_token = f"test_bg_{uuid4().hex[:8]}"
    candidate = settings.runs_dir / "sub" / run_token / "assets" / "classroom_scene.png"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"png-data")

    html = "<style>.scene{background-image:url('runs/sub/%s/assets/classroom_scene.png')}</style>" % run_token
    try:
        rewritten = agents._rewrite_html_asset_urls_for_local_render(html, asset_map={})
        assert "background-image:url('file://" in rewritten
        assert "classroom_scene.png" in rewritten
    finally:
        if candidate.exists():
            candidate.unlink()


def test_generate_html_payload_excludes_solution(monkeypatch) -> None:
    settings = replace(get_settings(), use_stub_agents=False)
    agents = AgentService(settings=settings)
    question = _build_question()
    layout = agents._stub_generate_layout(question)
    captured: dict[str, object] = {}

    def fake_run_agent(self, *, config, output_type, payload, agent_name):  # noqa: ANN001
        captured["payload"] = payload
        return GeneratedHtml(html_content="<div>ok</div>")

    monkeypatch.setattr(AgentService, "_run_agent", fake_run_agent)
    result = agents.generate_html(question, layout, asset_map={})

    assert result.html_content == "<div>ok</div>"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    question_payload = payload.get("question")
    assert isinstance(question_payload, dict)
    assert "solution" not in question_payload

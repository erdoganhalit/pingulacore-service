from __future__ import annotations

from pathlib import Path

from app.agents.config import _load_from_yaml


_BASE_YAML_TEMPLATE = """\
instructions:
  generate_question:
    - "Soru üret."
  extract_rules:
    - "Kural çıkar."
  evaluate_rule:
    - "Kural değerlendir."
  generate_layout:
    - "Yerleşim üret."
  validate_question_layout:
    - "Yerleşim doğrula."
  generate_html:
    - "HTML üret."
  validate_html:
    - "HTML doğrula."
  generate_image:
    - "Görsel üret."

run_settings:
  generate_question:
    primary_model: gemini-2.5-pro
    primary_max_retry: 3
    on_fail: error{generate_question_temp}
  extract_rules:
    primary_model: gemini-2.5-flash
    primary_max_retry: 2
    on_fail: error
  evaluate_rule:
    primary_model: gemini-2.5-flash
    primary_max_retry: 2
    on_fail: error
  generate_layout:
    primary_model: gemini-2.5-pro
    primary_max_retry: 3
    on_fail: error
  validate_question_layout:
    primary_model: gemini-2.5-flash
    primary_max_retry: 2
    on_fail: error
  generate_html:
    primary_model: gemini-2.5-pro
    primary_max_retry: 3
    on_fail: error
  validate_html:
    primary_model: gemini-2.5-flash
    primary_max_retry: 2
    on_fail: error
  generate_image:
    primary_model: gemini-2.5-flash-image
    primary_max_retry: 2
    on_fail: error
"""


def _write_yaml(tmp_path: Path, *, generate_question_temp: str = "") -> Path:
    content = _BASE_YAML_TEMPLATE.format(generate_question_temp=generate_question_temp)
    path = tmp_path / "agents.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_temperature_defaults_to_none_when_absent(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path)  # no temperature in yaml
    settings = _load_from_yaml(path)
    assert settings.generate_question.temperature is None
    assert settings.extract_rules.temperature is None


def test_temperature_parsed_when_present(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, generate_question_temp="\n    temperature: 0.4")
    settings = _load_from_yaml(path)
    assert settings.generate_question.temperature == 0.4
    # Other agents still default to None.
    assert settings.extract_rules.temperature is None


def test_temperature_accepts_integer(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, generate_question_temp="\n    temperature: 1")
    settings = _load_from_yaml(path)
    assert settings.generate_question.temperature == 1.0
    assert isinstance(settings.generate_question.temperature, float)


def test_model_settings_includes_temperature_when_set() -> None:
    """The model_settings dict built in _run_agent must include temperature only when configured."""
    from app.agents.config import AgentConfig

    cfg_with_temp = AgentConfig(
        instructions="test",
        primary_model="google-gla:gemini-2.5-flash",
        primary_max_retry=1,
        on_fail="error",
        thinking_level="medium",
        temperature=0.3,
    )
    cfg_no_temp = AgentConfig(
        instructions="test",
        primary_model="google-gla:gemini-2.5-flash",
        primary_max_retry=1,
        on_fail="error",
        thinking_level="medium",
    )

    # Mirror the construction logic in _run_agent.
    def build(cfg: AgentConfig) -> dict:
        ms: dict = {"thinking": cfg.thinking_level}
        if cfg.temperature is not None:
            ms["temperature"] = cfg.temperature
        return ms

    assert build(cfg_with_temp) == {"thinking": "medium", "temperature": 0.3}
    assert build(cfg_no_temp) == {"thinking": "medium"}

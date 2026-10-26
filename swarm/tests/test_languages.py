from typing import get_args

import pytest

from tb_swarm.analyst import AnalystRunner, Language
from tb_swarm.languages import DEFAULT_LANGUAGE, LANGUAGES, language_name


def test_english_is_the_default_and_every_language_has_a_prompt_name():
    assert DEFAULT_LANGUAGE == "en"
    assert {code: language_name(code) for code in LANGUAGES} == {"en": "English", "id": "Indonesian"}


def test_the_analyst_language_type_follows_the_registry():
    assert get_args(Language) == tuple(LANGUAGES)


def test_unknown_language_is_refused_with_the_valid_codes():
    with pytest.raises(ValueError, match="unknown language 'xx'; expected one of en, id"):
        language_name("xx")
    with pytest.raises(ValueError, match="unknown language"):
        AnalystRunner(object(), model_id="m", language="xx")


def test_a_runner_defaults_to_english():
    assert AnalystRunner(object(), model_id="m")._language == DEFAULT_LANGUAGE

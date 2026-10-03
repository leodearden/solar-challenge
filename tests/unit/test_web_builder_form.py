# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.builder_form, called directly with form values."""

import pytest

pytest.importorskip("flask")

from solar_challenge.web.builder_form import scenario_from_builder_form
from solar_challenge.web.shared import NotAJsonObject


class TestScenarioFromBuilderForm:
    """The fleet scenario document scenario_from_builder_form builds from a builder form, and its refusals."""

    @pytest.mark.parametrize(
        ("form", "type_name"),
        [
            pytest.param([1], "list", id="array"),
            pytest.param(None, "NoneType", id="null"),
        ],
    )
    def test_a_form_that_is_not_a_json_object_is_refused_naming_its_type(
        self, form: object, type_name: str
    ) -> None:
        """The web's shared NotAJsonObject refuses it as the "Builder form".

        Over HTTP this refusal is unreachable, because request_json_object refuses the
        body first, so this direct call is its only guard.
        """
        with pytest.raises(NotAJsonObject) as exc_info:
            scenario_from_builder_form(form)
        assert str(exc_info.value) == f"Builder form must be a JSON object, got {type_name}"

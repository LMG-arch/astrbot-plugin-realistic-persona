from pathlib import Path

import json
import pytest


class TestConfSchema:
    @pytest.fixture
    def schema(self):
        schema_path = Path(__file__).parent.parent / "_conf_schema.json"
        with open(schema_path, encoding="utf-8") as f:
            return json.load(f)

    def test_selfie_trigger_chance_has_min_max(self, schema):
        field = schema.get("selfie_trigger_chance", {})
        assert field.get("min") == 0
        assert field.get("max") == 1

    def test_insomnia_probability_has_min_max(self, schema):
        field = schema.get("insomnia_probability", {})
        assert field.get("min") == 0
        assert field.get("max") == 1

    def test_schedule_hour_has_min_max(self, schema):
        field = schema.get("schedule_hour", {})
        assert field.get("min") == 0
        assert field.get("max") == 23

    def test_publish_times_per_day_has_min_max(self, schema):
        field = schema.get("publish_times_per_day", {})
        assert field.get("min") == 1
        assert field.get("max") == 10

    def test_api_key_sensitive(self, schema):
        field = schema.get("api_key", {})
        assert field.get("obvious_hint") is True

    def test_openai_api_key_sensitive(self, schema):
        field = schema.get("openai_api_key", {})
        assert field.get("obvious_hint") is True

    def test_aliyun_api_key_sensitive(self, schema):
        field = schema.get("aliyun_api_key", {})
        assert field.get("obvious_hint") is True


class TestMetadataYaml:
    @pytest.fixture
    def metadata(self):
        import yaml

        yaml_path = Path(__file__).parent.parent / "metadata.yaml"
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_has_license(self, metadata):
        assert "license" in metadata

    def test_has_keywords(self, metadata):
        assert "keywords" in metadata
        assert isinstance(metadata["keywords"], list)
        assert len(metadata["keywords"]) > 0


class TestRequirementsTxt:
    @pytest.fixture
    def requirements(self):
        req_path = Path(__file__).parent.parent / "requirements.txt"
        with open(req_path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]

    def test_aiohttp_has_upper_bound(self, requirements):
        aiohttp_line = [r for r in requirements if r.startswith("aiohttp")][0]
        assert "<4.0.0" in aiohttp_line

    def test_pydantic_has_upper_bound(self, requirements):
        pydantic_line = [r for r in requirements if r.startswith("pydantic")][0]
        assert "<3.0.0" in pydantic_line

    def test_apscheduler_has_upper_bound(self, requirements):
        aps_line = [r for r in requirements if r.startswith("apscheduler")][0]
        assert "<4.0.0" in aps_line

    def test_all_deps_have_upper_bound(self, requirements):
        for req in requirements:
            pkg_name = req.split(">=")[0]
            assert "<" in req, f"{pkg_name} missing upper version bound"

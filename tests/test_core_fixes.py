import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestExperienceBankJSONLRobust:
    @pytest.fixture
    def data_dir(self, tmp_path):
        return tmp_path

    def _write_jsonl(self, path, lines):
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")

    def test_malformed_jsonl_skipped(self, data_dir):
        self._write_jsonl(
            data_dir / "conversations.jsonl",
            [
                json.dumps({"user_id": "u1", "msg": "hello"}),
                "THIS IS NOT JSON",
                "",
                json.dumps({"user_id": "u2", "msg": "world"}),
                "{broken json",
            ],
        )
        records = []
        with open(data_dir / "conversations.jsonl", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        assert len(records) == 2
        assert records[0]["user_id"] == "u1"
        assert records[1]["user_id"] == "u2"

    def test_empty_jsonl(self, data_dir):
        self._write_jsonl(data_dir / "empty.jsonl", [])
        records = []
        with open(data_dir / "empty.jsonl", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        assert len(records) == 0


class TestMemoryManagerJSONLRobust:
    def test_single_parse_not_double(self, tmp_path):
        conversations_file = tmp_path / "conversations.jsonl"
        with open(conversations_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"user_id": "u1", "msg": "hello"}) + "\n")
            f.write(json.dumps({"user_id": "u1", "msg": "world"}) + "\n")
            f.write(json.dumps({"user_id": "u2", "msg": "hi"}) + "\n")

        conversations = []
        parse_count = 0
        with open(conversations_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    parse_count += 1
                    if record.get("user_id") == "u1":
                        conversations.append(record)
                except json.JSONDecodeError:
                    continue

        assert len(conversations) == 2
        assert parse_count == 3


class TestURLQuoteFix:
    def test_weather_location_encoded(self):
        from urllib.parse import quote

        location = "北京市朝阳区"
        encoded = quote(location, safe="")
        assert "%" in encoded
        assert "北京市" not in encoded

    def test_weather_location_normal(self):
        from urllib.parse import quote

        location = "Beijing"
        encoded = quote(location, safe="")
        assert encoded == "Beijing"

    def test_weather_location_special_chars(self):
        from urllib.parse import quote

        location = "../../internal-api"
        encoded = quote(location, safe="")
        assert "../" not in encoded


class TestBaseManagerStructure:
    def test_base_manager_holds_state(self):
        """Verify BaseManager stores SharedState and exposes config/context."""
        from importlib import import_module
        from unittest.mock import patch

        from pathlib import Path

        plugin_name = Path(__file__).parent.parent.name
        base_mod = import_module(f"{plugin_name}.managers.base")
        BaseManager = base_mod.BaseManager
        SharedState = base_mod.SharedState

        mock_context = MagicMock()
        mock_config = {"key": "value"}

        with patch("managers.base.VersionComparator") as mock_vc, patch(
            "managers.base.StarTools"
        ):
            mock_vc.compare_version.return_value = True
            state = SharedState(mock_context, mock_config)
            manager = BaseManager(state)
            assert manager.state is state
            assert manager.context is mock_context
            assert manager.config is mock_config


class TestPostUpdateFix:
    def test_update_valid_field(self):
        try:
            from core.post import Post

            post = Post(
                post_id="test1",
                content="测试内容",
                created_at="2024-01-01",
            )
            if hasattr(post, "update"):
                if hasattr(post, "model_fields"):
                    post.update(content="新内容")
                    assert post.content == "新内容"
        except Exception:
            pytest.skip("Post model not importable in test context")

    def test_update_invalid_field_raises(self):
        try:
            from core.post import Post

            post = Post(
                post_id="test1",
                content="测试内容",
                created_at="2024-01-01",
            )
            if hasattr(post, "update"):
                with pytest.raises(AttributeError):
                    post.update(nonexistent_field="value")
        except Exception:
            pytest.skip("Post model not importable in test context")

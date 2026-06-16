import sys
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# Import via the plugin package namespace so relative imports resolve
PLUGIN_DIR = Path(__file__).parent.parent
PLUGIN_NAME = PLUGIN_DIR.name

from importlib import import_module

SharedState = import_module(f"{PLUGIN_NAME}.managers.base").SharedState
BaseManager = import_module(f"{PLUGIN_NAME}.managers.base").BaseManager
EmotionManager = import_module(f"{PLUGIN_NAME}.managers.emotion_manager").EmotionManager


class TestSharedState:
    def test_init(self, mock_config, mock_context):
        with patch("managers.base.VersionComparator") as mock_vc, patch(
            "managers.base.StarTools"
        ):
            mock_vc.compare_version.return_value = True
            state = SharedState(mock_context, mock_config)
            assert state.config is mock_config
            assert state.context is mock_context
            assert state.emotion_contexts == {}
            assert state.favorability == {}

    def test_config_values_extracted(self, mock_config, mock_context):
        with patch("managers.base.VersionComparator") as mock_vc, patch(
            "managers.base.StarTools"
        ):
            mock_vc.compare_version.return_value = True
            state = SharedState(mock_context, mock_config)
            assert state.weather_location == "Beijing"
            assert state.persona_name == "测试角色"
            assert state.enable_emotion_detection is True
            assert state.enable_qzone is False

    def test_config_defaults(self, mock_config, mock_context):
        with patch("managers.base.VersionComparator") as mock_vc, patch(
            "managers.base.StarTools"
        ):
            mock_vc.compare_version.return_value = True
            state = SharedState(mock_context, mock_config)
            # Values not in mock_config should get defaults
            assert state.selfie_trigger_chance == 0.1  # set in mock_config
            assert state.enable_life_simulation is True  # set in mock_config
            assert state.idle_greeting_delay == 300  # set in mock_config


class TestBaseManager:
    def test_state_and_properties(self, mock_config, mock_context):
        with patch("managers.base.VersionComparator") as mock_vc, patch(
            "managers.base.StarTools"
        ):
            mock_vc.compare_version.return_value = True
            state = SharedState(mock_context, mock_config)
            manager = BaseManager(state)
            assert manager.state is state
            assert manager.context is mock_context
            assert manager.config is mock_config


class TestEmotionManager:
    def _make_state(self, mock_config, mock_context):
        with patch("managers.base.VersionComparator") as mock_vc, patch(
            "managers.base.StarTools"
        ):
            mock_vc.compare_version.return_value = True
            return SharedState(mock_context, mock_config)

    @pytest.mark.asyncio
    async def test_get_context_creates_new(self, mock_config, mock_context):
        state = self._make_state(mock_config, mock_context)
        manager = EmotionManager(state)
        ctx = await manager.get_context("session1")
        assert ctx is not None
        assert "session1" in state.emotion_contexts

    @pytest.mark.asyncio
    async def test_get_context_returns_existing(self, mock_config, mock_context):
        state = self._make_state(mock_config, mock_context)
        manager = EmotionManager(state)
        ctx1 = await manager.get_context("session1")
        ctx2 = await manager.get_context("session1")
        assert ctx1 is ctx2

    @pytest.mark.asyncio
    async def test_process_emotion_disabled(self, mock_config, mock_context):
        mock_config["enable_emotion_detection"] = False
        state = self._make_state(mock_config, mock_context)
        manager = EmotionManager(state)

        mock_event = MagicMock()
        mock_event.message_obj.message_str = "你好"
        mock_event.get_session_id.return_value = "session1"

        result = await manager.process_emotion_and_events(mock_event)
        assert result["emotion"] is None
        assert result["should_selfie"] is False

    @pytest.mark.asyncio
    async def test_process_emotion_empty_message(self, mock_config, mock_context):
        state = self._make_state(mock_config, mock_context)
        manager = EmotionManager(state)

        mock_event = MagicMock()
        mock_event.message_obj.message_str = ""
        mock_event.get_session_id.return_value = "session1"

        result = await manager.process_emotion_and_events(mock_event)
        assert result["emotion"] is None

    @pytest.mark.asyncio
    async def test_update_favorability_bounded(self, mock_config, mock_context):
        state = self._make_state(mock_config, mock_context)
        manager = EmotionManager(state)
        state.favorability["session1"] = 99.0

        mock_event = MagicMock()
        mock_event.get_session_id.return_value = "session1"
        mock_event.message_obj.message_str = ""

        await manager.update_favorability(mock_event)
        assert state.favorability["session1"] <= 100.0

    @pytest.mark.asyncio
    async def test_update_favorability_min_zero(self, mock_config, mock_context):
        state = self._make_state(mock_config, mock_context)
        manager = EmotionManager(state)
        state.favorability["session1"] = 0.1

        mock_event = MagicMock()
        mock_event.get_session_id.return_value = "session1"
        mock_event.message_obj.message_str = ""

        await manager.update_favorability(mock_event)
        assert state.favorability["session1"] >= 0.0

    @pytest.mark.asyncio
    async def test_get_status_returns_string(self, mock_config, mock_context):
        state = self._make_state(mock_config, mock_context)
        manager = EmotionManager(state)
        status = await manager.get_status("session1")
        assert isinstance(status, str)
        assert "暂无情绪数据" in status

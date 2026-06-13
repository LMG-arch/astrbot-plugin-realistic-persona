import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from types import ModuleType

import pytest

PLUGIN_DIR = Path(__file__).parent.parent
PLUGIN_NAME = PLUGIN_DIR.name

# Register the plugin directory as a package so relative imports
# (e.g. from ..context_events in managers/base.py) resolve correctly.
# This makes "managers" and "core" subpackages of the plugin package.
if PLUGIN_NAME not in sys.modules:
    pkg = ModuleType(PLUGIN_NAME)
    pkg.__path__ = [str(PLUGIN_DIR)]
    pkg.__package__ = PLUGIN_NAME
    sys.modules[PLUGIN_NAME] = pkg

# Ensure managers is recognized as a subpackage (both as PLUGIN_NAME.managers
# and as top-level "managers" so `from managers.base import ...` works)
managers_key = f"{PLUGIN_NAME}.managers"
if managers_key not in sys.modules:
    mgr_pkg = ModuleType(managers_key)
    mgr_pkg.__path__ = [str(PLUGIN_DIR / "managers")]
    mgr_pkg.__package__ = managers_key
    sys.modules[managers_key] = mgr_pkg
# Alias top-level "managers" to the same package object
if "managers" not in sys.modules:
    sys.modules["managers"] = sys.modules[managers_key]

# Same for core
core_key = f"{PLUGIN_NAME}.core"
if core_key not in sys.modules:
    core_pkg = ModuleType(core_key)
    core_pkg.__path__ = [str(PLUGIN_DIR / "core")]
    core_pkg.__package__ = core_key
    sys.modules[core_key] = core_pkg
if "core" not in sys.modules:
    sys.modules["core"] = sys.modules[core_key]

sys.path.insert(0, str(PLUGIN_DIR.parent))
sys.path.insert(0, str(PLUGIN_DIR))

ASTRBOT_DIR = Path(__file__).parent.parent.parent.parent.parent / "astrbot"
if (ASTRBOT_DIR / "__init__.py").exists():
    sys.path.insert(0, str(ASTRBOT_DIR.parent))

if "astrbot" not in sys.modules:
    astrbot_mod = ModuleType("astrbot")
    sys.modules["astrbot"] = astrbot_mod

    api_mod = ModuleType("astrbot.api")
    mock_logger = MagicMock()
    mock_logger.info = MagicMock()
    mock_logger.debug = MagicMock()
    mock_logger.warning = MagicMock()
    mock_logger.error = MagicMock()
    api_mod.logger = mock_logger
    api_mod.AstrBotConfig = dict
    sys.modules["astrbot.api"] = api_mod

    event_mod = ModuleType("astrbot.api.event")
    event_mod.AstrMessageEvent = MagicMock
    sys.modules["astrbot.api.event"] = event_mod

    provider_mod = ModuleType("astrbot.api.provider")
    sys.modules["astrbot.api.provider"] = provider_mod

    star_mod = ModuleType("astrbot.api.star")
    star_mod.Context = MagicMock
    star_mod.Star = MagicMock
    star_mod.StarTools = MagicMock
    star_mod.register = MagicMock()
    sys.modules["astrbot.api.star"] = star_mod

    core_mod = ModuleType("astrbot.core")
    sys.modules["astrbot.core"] = core_mod

    message_mod = ModuleType("astrbot.core.message")
    sys.modules["astrbot.core.message"] = message_mod

    components_mod = ModuleType("astrbot.core.message.components")
    components_mod.At = MagicMock
    components_mod.Image = MagicMock
    components_mod.Reply = MagicMock
    components_mod.BaseMessageComponent = MagicMock
    sys.modules["astrbot.core.message.components"] = components_mod

    config_mod = ModuleType("astrbot.core.config")
    sys.modules["astrbot.core.config"] = config_mod

    default_mod = ModuleType("astrbot.core.config.default")
    default_mod.VERSION = "4.23.6"
    sys.modules["astrbot.core.config.default"] = default_mod

    platform_mod = ModuleType("astrbot.core.platform")
    platform_mod.AstrMessageEvent = MagicMock
    sys.modules["astrbot.core.platform"] = platform_mod

    sources_mod = ModuleType("astrbot.core.platform.sources")
    sys.modules["astrbot.core.platform.sources"] = sources_mod

    aiocqhttp_mod = ModuleType("astrbot.core.platform.sources.aiocqhttp")
    sys.modules["astrbot.core.platform.sources.aiocqhttp"] = aiocqhttp_mod

    aiocqhttp_event_mod = ModuleType(
        "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event"
    )
    aiocqhttp_event_mod.AiocqhttpMessageEvent = MagicMock
    sys.modules[
        "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event"
    ] = aiocqhttp_event_mod

    aiocqhttp_adapter_mod = ModuleType(
        "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter"
    )
    aiocqhttp_adapter_mod.AiocqhttpAdapter = MagicMock
    sys.modules[
        "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter"
    ] = aiocqhttp_adapter_mod

    utils_mod = ModuleType("astrbot.core.utils")
    sys.modules["astrbot.core.utils"] = utils_mod

    version_mod = ModuleType("astrbot.core.utils.version_comparator")
    version_mod.VersionComparator = MagicMock()
    sys.modules["astrbot.core.utils.version_comparator"] = version_mod

    message_mod = ModuleType("astrbot.api.message_components")
    sys.modules["astrbot.api.message_components"] = message_mod


class MockConfig(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def save_config(self):
        pass


class MockContext:
    def __init__(self):
        self.get_using_provider = MagicMock(return_value=None)
        self.get_provider_by_id = MagicMock(return_value=None)
        self.get_config = MagicMock(return_value={})
        self.send_message = AsyncMock()
        self.get_all_stars = MagicMock(return_value=[])
        self.conversation_manager = MagicMock()


@pytest.fixture
def mock_config():
    return MockConfig(
        enable_emotion_detection=True,
        enable_auto_selfie=False,
        selfie_trigger_chance=0.1,
        enable_proactive_messages=False,
        idle_greeting_delay=300,
        enable_proactive_sharing=False,
        proactive_share_interval_minutes=60,
        enable_context_events=False,
        enable_life_simulation=True,
        persona_name="测试角色",
        persona_profile="这是一个测试角色",
        weather_location="Beijing",
        schedule_hour=7,
        news_hour=7,
        news_topics=["科技"],
        enable_async_thinking=False,
        think_interval_minutes=30,
        activity_interval_minutes=60,
        enable_qzone=False,
        enable_auto_profile_update=False,
        enable_news_getter=False,
        proactive_target_sessions="",
        diary_provider_id="",
    )


@pytest.fixture
def mock_context():
    return MockContext()

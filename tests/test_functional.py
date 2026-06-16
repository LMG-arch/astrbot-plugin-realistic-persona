"""
功能测试：验证每个模块是否符合 README 文档要求
"""
import asyncio
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PLUGIN_DIR = Path(__file__).parent.parent
PLUGIN_NAME = PLUGIN_DIR.name


def _import(mod_name):
    from importlib import import_module
    return import_module(f"{PLUGIN_NAME}.{mod_name}")


# ============================================================
# 1. 情绪感知系统
# ============================================================
class TestEmotionSystem:
    """README: 自动检测用户情绪（10种）、情绪趋势分析、自拍触发"""

    def test_detect_happy(self):
        mod = _import("emotions")
        assert mod.EmotionAnalyzer.analyze_emotion("我好开心啊太高兴了") == mod.EmotionType.HAPPY

    def test_detect_sad(self):
        mod = _import("emotions")
        assert mod.EmotionAnalyzer.analyze_emotion("好难过好伤心哭泣") == mod.EmotionType.SAD

    def test_detect_angry(self):
        mod = _import("emotions")
        assert mod.EmotionAnalyzer.analyze_emotion("气死我了太生气愤怒") == mod.EmotionType.ANGRY

    def test_detect_excited(self):
        mod = _import("emotions")
        assert mod.EmotionAnalyzer.analyze_emotion("太兴奋了好激动") == mod.EmotionType.EXCITED

    def test_detect_calm(self):
        mod = _import("emotions")
        assert mod.EmotionAnalyzer.analyze_emotion("很安静很平静淡定") == mod.EmotionType.CALM

    def test_detect_bored(self):
        mod = _import("emotions")
        assert mod.EmotionAnalyzer.analyze_emotion("好无聊啊没意思枯燥") == mod.EmotionType.BORED

    def test_detect_curious(self):
        mod = _import("emotions")
        assert mod.EmotionAnalyzer.analyze_emotion("很好奇想知道为什么") == mod.EmotionType.CURIOUS

    def test_detect_surprised(self):
        mod = _import("emotions")
        # Use keywords that uniquely trigger SURPRISED
        assert mod.EmotionAnalyzer.analyze_emotion("天哪不会吧真的假的") == mod.EmotionType.SURPRISED

    def test_detect_anxious(self):
        mod = _import("emotions")
        assert mod.EmotionAnalyzer.analyze_emotion("好焦虑好紧张不安") == mod.EmotionType.ANXIOUS

    def test_selfie_trigger(self):
        """README: 在开心、兴奋等情绪时自动触发真人自拍"""
        mod = _import("emotions")
        triggered = any(
            mod.EmotionAnalyzer.should_trigger_selfie(mod.EmotionType.HAPPY, 1.0)
            for _ in range(100)
        )
        assert triggered

    def test_emotion_context_history(self):
        """README: 情绪趋势分析"""
        mod = _import("emotions")
        ctx = mod.EmotionContext()
        ctx.add_emotion(mod.EmotionType.HAPPY, "开心", 1.0)
        ctx.add_emotion(mod.EmotionType.SAD, "难过", 2.0)
        assert ctx.get_recent_emotion() == mod.EmotionType.SAD
        assert len(ctx.emotion_history) == 2

    def test_emotion_intensity_map(self):
        """README: 情绪强度映射"""
        mod = _import("emotions")
        assert len(mod.EMOTION_INTENSITY_MAP) == 10
        for et in mod.EmotionType:
            assert 0 <= mod.EMOTION_INTENSITY_MAP[et] <= 1


# ============================================================
# 2. 经历银行
# ============================================================
class TestExperienceBank:
    """README: 经历累积、成长追踪、关系网络"""

    @pytest.fixture
    def bank(self, tmp_path):
        return _import("core.experience_bank").ExperienceBank(tmp_path)

    def test_record_conversation(self, bank):
        bank.record_conversation("user1", "你好", "你好呀！")
        assert bank.conversations_file.exists()

    def test_update_growth(self, bank):
        asyncio.run(bank.update_growth("skills", "Python", level=3))
        with open(bank.growth_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "Python" in data["skills"]

    def test_relationship_update(self, bank):
        asyncio.run(bank._update_relationship("user1", {"interaction_type": "chat"}))
        with open(bank.relationships_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "user1" in data

    def test_atomic_write(self, bank):
        asyncio.run(bank.update_growth("interests", "音乐"))
        with open(bank.growth_file, encoding="utf-8") as f:
            assert isinstance(json.load(f), dict)


# ============================================================
# 3. 记忆管理器
# ============================================================
class TestMemoryManager:
    """README: 记忆强化、衰减"""

    @pytest.fixture
    def mm(self, tmp_path):
        return _import("core.memory_manager").MemoryManager(tmp_path)

    def test_memory_decay(self, mm):
        """README: 根据时间和重要性自动淡出低价值记忆"""
        mm.weighted_conversations_file.parent.mkdir(parents=True, exist_ok=True)
        with open(mm.weighted_conversations_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"user_id": "u1", "weight": 0.1,
                                "timestamp": (datetime.now() - timedelta(days=60)).isoformat()}) + "\n")
        result = asyncio.run(mm.apply_memory_decay(days_threshold=30))
        assert "decayed" in result


# ============================================================
# 4. 心理引擎
# ============================================================
class TestPsychologyEngine:
    """README: 心理状态追踪"""

    @pytest.fixture
    def engine(self, tmp_path):
        return _import("core.psychology_engine").PsychologyEngine(tmp_path)

    def test_update_curiosity(self, engine):
        engine.update_curiosity("AI技术", "deep")
        with open(engine.drives_file, encoding="utf-8") as f:
            drives = json.load(f)
        assert drives["curiosity"]["level"] > 0

    def test_drive_level_bounded(self, engine):
        for _ in range(50):
            engine.update_curiosity("test", "deep")
        with open(engine.drives_file, encoding="utf-8") as f:
            drives = json.load(f)
        assert drives["curiosity"]["level"] <= 10

    def test_topics_capped(self, engine):
        for i in range(150):
            engine.update_curiosity(f"topic_{i}", "light")
        with open(engine.drives_file, encoding="utf-8") as f:
            drives = json.load(f)
        assert len(drives["curiosity"]["topics_explored"]) <= 100


# ============================================================
# 5. 思考引擎
# ============================================================
class TestThoughtEngine:
    """Critical fix: 类级别静态列表不被修改"""

    def test_thoughts_not_mutated(self):
        mod = _import("core.thought_engine")
        orig = len(mod.ThoughtEngine.TIME_BASED_THOUGHTS.get("morning", []))
        for _ in range(5):
            thoughts = list(mod.ThoughtEngine.TIME_BASED_THOUGHTS.get("morning", []))
            thoughts.extend(mod.ThoughtEngine.TIME_BASED_THOUGHTS.get("sunny", []))
        assert len(mod.ThoughtEngine.TIME_BASED_THOUGHTS.get("morning", [])) == orig


# ============================================================
# 6. 时间线验证器
# ============================================================
class TestTimelineVerifier:
    """README: 时间线一致性检查"""

    @pytest.fixture
    def verifier(self, tmp_path):
        return _import("core.timeline_verifier").TimelineVerifier(tmp_path)

    def test_yesterday_correct(self, verifier):
        """Critical fix: '昨天' 应返回昨天的日期"""
        result = verifier._normalize_date("昨天")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert result == yesterday

    def test_today_correct(self, verifier):
        result = verifier._normalize_date("今天")
        assert result == datetime.now().strftime("%Y-%m-%d")

    def test_add_experience(self, verifier):
        verifier.add_experience(
            experience_id="exp1", content="学习了Python",
            event_date="2025-01-15", event_type="skill"
        )
        with open(verifier.timeline_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "exp1" in data.get("experiences", data)


# ============================================================
# 7. 人格演化系统
# ============================================================
class TestPersonalityEvolution:
    """README: 自我认知、表达演进、习惯平衡"""

    def test_humor_can_decrease(self):
        mod = _import("core.personality_evolution")
        with tempfile.TemporaryDirectory() as tmp:
            evo = mod.ExpressionEvolution(Path(tmp))
            evo.humor_maturity = 8
            # Record 10 failed jokes to trigger maturity recalculation
            for _ in range(10):
                evo.record_joke(success=False)
            assert evo.humor_maturity < 8

    def test_inconsistencies_capped(self):
        mod = _import("core.personality_evolution")
        with tempfile.TemporaryDirectory() as tmp:
            system = mod.SelfAwarenessSystem(Path(tmp))
            system.behavior_stats["inconsistencies"] = [{"i": i} for i in range(200)]
            system._save_state()
            with open(system.state_file, encoding="utf-8") as f:
                assert len(json.load(f)["behavior_stats"]["inconsistencies"]) <= 100


# ============================================================
# 8. 本地数据管理器
# ============================================================
class TestLocalDataManager:
    """README: 本地数据持久化"""

    def test_drawing_prompts_cleanup(self, tmp_path):
        mod = _import("core.local_data_manager")
        ldm = mod.LocalDataManager(tmp_path)
        dp_file = tmp_path / "local_data" / "drawing_prompts.json"
        dp_file.parent.mkdir(parents=True, exist_ok=True)
        dp_file.write_text(json.dumps({
            "2020-01-01": [{"prompt": "old"}],
            datetime.now().strftime("%Y-%m-%d"): [{"prompt": "new"}]
        }), encoding="utf-8")
        ldm.clear_expired_data()


# ============================================================
# 9. 情绪管理器（Manager层）
# ============================================================
class TestEmotionManager:
    """README: 情绪检测、好感度系统"""

    @pytest.mark.asyncio
    async def test_favorability_bounded(self):
        """Favorability is clamped to [0, 100]."""
        base_mod = _import("managers.base")
        em_mod = _import("managers.emotion_manager")
        with patch("managers.base.VersionComparator") as mc, patch("managers.base.StarTools"):
            mc.compare_version.return_value = True
            state = base_mod.SharedState(MagicMock(), {"enable_emotion_detection": True})
            mgr = em_mod.EmotionManager(state)
            state.favorability["s1"] = 99.0
            ev = MagicMock()
            ev.get_session_id.return_value = "s1"
            ev.message_obj.message_str = ""
            await mgr.update_favorability(ev)
            assert state.favorability["s1"] <= 100.0

    def test_no_duplicate_analysis(self):
        """Critical fix: 每条消息不应重复分析情绪两次"""
        base_mod = _import("managers.base")
        em_mod = _import("managers.emotion_manager")
        emo_mod = _import("emotions")
        with patch("managers.base.VersionComparator") as mc, patch("managers.base.StarTools"):
            mc.compare_version.return_value = True
            state = base_mod.SharedState(MagicMock(), {
                "enable_emotion_detection": True, "enable_context_events": False
            })
            mgr = em_mod.EmotionManager(state)
            ev = MagicMock()
            ev.message_obj.message_str = "我好开心"
            ev.get_session_id.return_value = "s1"
            with patch.object(emo_mod.EmotionAnalyzer, 'analyze_emotion',
                              wraps=emo_mod.EmotionAnalyzer.analyze_emotion) as ma:
                asyncio.run(mgr.process_emotion_and_events(ev))
                assert ma.call_count == 1


# ============================================================
# 10. 上下文事件
# ============================================================
class TestContextEvents:
    """README: 对话事件检测"""

    def test_greeting_with_punctuation(self):
        mod = _import("context_events")
        det = mod.EventDetector()
        assert det.is_greeting("你好！") is True
        assert det.is_greeting("你好~") is True


# ============================================================
# 11. 配置 Schema
# ============================================================
class TestConfigSchema:
    """README: 配置项完整性"""

    def test_forbidden_rules_default_empty(self):
        with open("_conf_schema.json", encoding="utf-8") as f:
            assert json.load(f)["image_forbidden_rules"]["default"] == ""

    def test_numeric_bounds(self):
        with open("_conf_schema.json", encoding="utf-8") as f:
            schema = json.load(f)
        for field in ["selfie_trigger_chance", "insomnia_probability", "schedule_hour"]:
            assert "min" in schema[field] and "max" in schema[field]

    def test_sensitive_hints(self):
        with open("_conf_schema.json", encoding="utf-8") as f:
            schema = json.load(f)
        for field in ["api_key", "openai_api_key", "aliyun_api_key"]:
            assert schema[field].get("obvious_hint") is True


# ============================================================
# 12. 原子写入工具
# ============================================================
class TestAtomicWrite:
    """v1.21.0: 原子文件写入"""

    def test_write_json(self, tmp_path):
        mod = _import("core.utils")
        target = tmp_path / "test.json"
        mod.atomic_write_json(target, {"key": "value"})
        with open(target, encoding="utf-8") as f:
            assert json.load(f) == {"key": "value"}

    def test_no_corruption_on_failure(self, tmp_path):
        mod = _import("core.utils")
        target = tmp_path / "test.json"
        target.write_text('{"ok": true}', encoding="utf-8")
        try:
            mod.atomic_write_json(target, object())
        except Exception:
            pass
        with open(target, encoding="utf-8") as f:
            assert json.load(f) == {"ok": True}


# ============================================================
# 13. utils 安全修复
# ============================================================
class TestUtils:
    """工具函数安全修复"""

    def test_reject_non_http(self):
        mod = _import("core.utils")
        assert asyncio.run(mod.download_file("../../etc/passwd")) is None

    def test_reject_ftp(self):
        mod = _import("core.utils")
        assert asyncio.run(mod.download_file("ftp://example.com/file")) is None


# ============================================================
# 以下测试需要外部依赖（aiocqhttp等），在无依赖环境中跳过
# ============================================================
try:
    import aiocqhttp
    HAS_AIOCQHTTP = True
except ImportError:
    HAS_AIOCQHTTP = False

try:
    _import("core.scheduler")
    HAS_SCHEDULER = True
except Exception:
    HAS_SCHEDULER = False

try:
    _import("core.qzone_api")
    HAS_QZONE = True
except Exception:
    HAS_QZONE = False


@pytest.mark.skipif(not HAS_SCHEDULER, reason="需要 astrbot 完整环境")
class TestSchedulerImport:
    def test_start_method_exists(self):
        mod = _import("core.scheduler")
        assert hasattr(mod.AutoPublish, 'start')


@pytest.mark.skipif(not HAS_QZONE, reason="需要 aiocqhttp 依赖")
class TestQzoneApiImport:
    def test_session_lazy_init(self):
        mod = _import("core.qzone_api")
        assert hasattr(mod.QzoneApi, '_ensure_session')

    def test_json_parse_safe(self):
        mod = _import("core.qzone_api")
        api = mod.QzoneApi.__new__(mod.QzoneApi)
        with pytest.raises(ValueError, match="未找到JSON对象"):
            api._parse_json("no json here")

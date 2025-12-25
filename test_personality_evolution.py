# -*- coding: utf-8 -*-
"""
人格演化系统测试脚本
演示各个子系统的功能
"""
from pathlib import Path
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from core.personality_evolution import (
    SelfAwarenessSystem,
    ExpressionEvolution,
    HabitBalanceSystem,
    PersonalityEvolutionManager
)


def test_self_awareness():
    """测试自我认知系统"""
    print("\n" + "="*50)
    print("测试自我认知系统")
    print("="*50)
    
    data_dir = Path("./test_data/self_awareness")
    system = SelfAwarenessSystem(data_dir)
    
    print(f"\n初始自我描述：")
    print(system.get_self_summary())
    
    # 模拟行为记录
    print("\n模拟记录10次行为...")
    for i in range(10):
        system.record_behavior("conversation", f"我很好奇这个问题{i}")
    
    # 检查一致性
    print("\n检查自我描述一致性：")
    consistency = system.check_consistency()
    print(f"- 总互动次数: {consistency['total_interactions']}")
    if consistency.get('trait_rates'):
        print("- 特质表现率:")
        for trait, rate in consistency['trait_rates'].items():
            print(f"  · {trait}: {rate:.2%}")
    
    # 演化特质
    print("\n尝试添加新特质...")
    system.evolve_trait("有条理", "经常系统性地思考问题", gradual=True)


def test_expression_evolution():
    """测试表达演进系统"""
    print("\n" + "="*50)
    print("测试表达演进系统")
    print("="*50)
    
    data_dir = Path("./test_data/expression")
    system = ExpressionEvolution(data_dir)
    
    print(f"\n初始表达能力：")
    print(f"- 词汇水平: {system.vocabulary_level}/10")
    print(f"- 幽默成熟度: {system.humor_maturity}/10")
    print(f"- 句式复杂度: {system.sentence_complexity}/10")
    
    # 学习新内容
    print("\n从内容中学习新词汇...")
    sample_text = "今天学习了机器学习、深度学习和自然语言处理等人工智能技术"
    system.learn_from_content(sample_text)
    print(f"学习后词汇数: {len(system.learned_words)}")
    print(f"词汇水平: {system.vocabulary_level}/10")
    
    # 记录笑话效果
    print("\n模拟讲笑话...")
    for i in range(5):
        success = i % 2 == 0  # 50%成功率
        system.record_joke(success)
    print(f"笑话统计: {system.jokes_successful}/{system.jokes_told} 成功")
    print(f"幽默成熟度: {system.humor_maturity}/10")


def test_habit_balance():
    """测试习惯平衡系统"""
    print("\n" + "="*50)
    print("测试习惯平衡系统")
    print("="*50)
    
    data_dir = Path("./test_data/habits")
    system = HabitBalanceSystem(data_dir)
    
    print(f"\n当前状态：")
    print(f"- 变化阶段: {system.change_phase}")
    print(f"- 阶段天数: {system.days_in_phase}")
    
    print(f"\n核心习惯:")
    for habit in system.core_habits:
        print(f"  · {habit}")
    
    print(f"\n临时习惯:")
    for habit in system.temporary_habits:
        print(f"  · {habit}")
    
    # 测试惊喜控制
    print("\n测试惊喜控制...")
    should_surprise = system.should_trigger_surprise()
    print(f"- 是否应触发惊喜: {should_surprise}")
    if should_surprise:
        system.record_surprise()
        print("- 已记录惊喜事件")


def test_personality_manager():
    """测试人格演化管理器"""
    print("\n" + "="*50)
    print("测试人格演化管理器")
    print("="*50)
    
    data_dir = Path("./test_data/personality")
    manager = PersonalityEvolutionManager(data_dir)
    
    # 模拟每日例行检查
    print("\n执行每日例行检查...")
    manager.daily_routine()
    
    # 模拟交互
    print("\n模拟用户交互...")
    user_msg = "你好！我今天学习了Python编程"
    ai_response = "哇！Python是一门很有趣的语言呢！"
    manager.process_interaction(user_msg, ai_response)
    
    # 获取人格摘要
    print("\n人格状态摘要：")
    summary = manager.get_personality_summary()
    print(f"- 自我描述: {summary['self_description']}")
    print(f"- 表达能力: {summary['expression_levels']}")
    print(f"- 当前阶段: {summary['current_phase']}")
    print(f"- 核心习惯数: {len(summary['core_habits'])}")
    print(f"- 临时习惯数: {len(summary['temporary_habits'])}")


if __name__ == "__main__":
    print("\n" + "🎭 人格演化系统功能演示 🎭".center(60, "="))
    
    # 创建测试数据目录
    Path("./test_data").mkdir(exist_ok=True)
    
    try:
        test_self_awareness()
        test_expression_evolution()
        test_habit_balance()
        test_personality_manager()
        
        print("\n" + "="*60)
        print("✅ 所有测试完成！")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()

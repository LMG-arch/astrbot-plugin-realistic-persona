"""
QQ空间模块诊断脚本
检查配置和模块可用性
"""

import sys
from pathlib import Path

# 添加项目路径
plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

print("=" * 60)
print("QQ空间模块诊断工具".center(50))
print("=" * 60)

# 1. 检查核心模块文件是否存在
print("\n【步骤 1】检查核心模块文件")
print("-" * 60)

core_dir = plugin_dir / "core"
required_files = [
    "llm_action.py",
    "operate.py",
    "qzone_api.py",
    "scheduler.py",
    "utils.py",
]

missing_files = []
for file_name in required_files:
    file_path = core_dir / file_name
    exists = file_path.exists()
    status = "✅" if exists else "❌"
    print(f"{status} {file_name}: {'存在' if exists else '缺失'}")
    if not exists:
        missing_files.append(file_name)

if missing_files:
    print(f"\n⚠️  警告：缺失 {len(missing_files)} 个核心文件")
    print("   这会导致 QZONE_AVAILABLE = False")
    print(f"   缺失文件：{', '.join(missing_files)}")
else:
    print("\n✅ 所有核心模块文件完整")

# 2. 尝试导入模块
print("\n【步骤 2】尝试导入QQ空间模块")
print("-" * 60)

QZONE_AVAILABLE = False
import_error = None

try:
    from core.llm_action import LLMAction  # noqa: F401

    print("✅ LLMAction 导入成功")
except ImportError as e:
    print(f"❌ LLMAction 导入失败: {e}")
    import_error = e

try:
    from core.operate import PostOperator  # noqa: F401

    print("✅ PostOperator 导入成功")
except ImportError as e:
    print(f"❌ PostOperator 导入失败: {e}")
    import_error = e

try:
    from core.qzone_api import Qzone  # noqa: F401

    print("✅ Qzone 导入成功")
except ImportError as e:
    print(f"❌ Qzone 导入失败: {e}")
    import_error = e

try:
    from core.scheduler import AutoPublish  # noqa: F401

    print("✅ AutoPublish 导入成功")
except ImportError as e:
    print(f"❌ AutoPublish 导入失败: {e}")
    import_error = e

try:
    from core.utils import get_image_urls  # noqa: F401

    print("✅ get_image_urls 导入成功")
    QZONE_AVAILABLE = True
except ImportError as e:
    print(f"❌ get_image_urls 导入失败: {e}")
    import_error = e

if QZONE_AVAILABLE:
    print("\n✅ QQ空间模块完全可用 (QZONE_AVAILABLE = True)")
else:
    print("\n❌ QQ空间模块不可用 (QZONE_AVAILABLE = False)")
    if import_error:
        print(f"   错误原因：{import_error}")

# 3. 检查配置文件
print("\n【步骤 3】检查配置文件")
print("-" * 60)

config_file = plugin_dir / "_conf_schema.json"
if config_file.exists():
    print(f"✅ 配置文件存在: {config_file}")

    import json

    try:
        with open(config_file, encoding="utf-8") as f:
            config_schema = json.load(f)

        # 检查关键配置项
        qzone_configs = {
            "enable_qzone": config_schema.get("enable_qzone", {}).get("default", False),
            "publish_times_per_day": config_schema.get("publish_times_per_day", {}).get(
                "default", 0
            ),
            "insomnia_probability": config_schema.get("insomnia_probability", {}).get(
                "default", 0
            ),
        }

        print("\n配置项默认值：")
        for key, value in qzone_configs.items():
            print(f"  - {key}: {value}")

    except Exception as e:
        print(f"❌ 解析配置文件失败: {e}")
else:
    print(f"❌ 配置文件不存在: {config_file}")

# 4. 诊断总结
print("\n" + "=" * 60)
print("诊断总结".center(50))
print("=" * 60)

issues = []
solutions = []

if missing_files:
    issues.append(f"缺失核心文件: {', '.join(missing_files)}")
    solutions.append("从原始插件仓库复制缺失的文件到 core/ 目录")

if not QZONE_AVAILABLE:
    issues.append("QQ空间模块导入失败")
    if import_error:
        issues.append(f"导入错误: {import_error}")
    solutions.append("检查依赖是否安装完整（aiocqhttp, pillowmd等）")
    solutions.append("查看详细错误信息并解决导入问题")

if not issues:
    print("\n✅ 未发现问题，QQ空间模块状态正常")
    print("\n如果功能仍然无法使用，请检查：")
    print("  1. 在插件配置中设置 enable_qzone = true")
    print("  2. 设置 publish_times_per_day > 0 或 insomnia_probability > 0")
    print("  3. 确保使用的是 aiocqhttp 平台")
    print("  4. 等待插件初始化完成后再使用命令")
else:
    print(f"\n⚠️  发现 {len(issues)} 个问题：")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")

    print("\n💡 建议的解决方案：")
    for i, solution in enumerate(solutions, 1):
        print(f"  {i}. {solution}")

# 5. 快速启用指南
print("\n" + "=" * 60)
print("快速启用QQ空间功能".center(50))
print("=" * 60)

print("""
1️⃣ 确保模块文件完整
   检查 core/ 目录下是否有以下文件：
   - llm_action.py
   - operate.py
   - qzone_api.py
   - scheduler.py
   - utils.py

2️⃣ 在插件配置中启用QQ空间
   设置以下配置项：
   • enable_qzone: true
   • publish_times_per_day: 1 (或更多)
   • publish_time_ranges: ["9-12", "14-18", "19-22"]

3️⃣ 重启 AstrBot
   重新加载插件使配置生效

4️⃣ 查看日志确认
   应该看到：
   • QQ空间配置: enable_qzone=True, publish_times_per_day=1
   • QQ空间自动发说说模块加载完毕！

5️⃣ 使用命令测试
   /写说说 今天天气真好
""")

print("=" * 60)

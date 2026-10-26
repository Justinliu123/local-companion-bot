# src/companion/: 陪伴机器人核心模块参考实现
#
# 这是一个**参考骨架**，用于说明模块间的协作方式。
# 实际部署时按目标机器的 Python 版本和依赖安装后调整。
#
# 文件结构建议：
#   astrbot/
#   └── companion/
#       ├── __init__.py
#       ├── emotion.py       # 情绪状态机
#       ├── proactive.py     # 主动关怀调度
#       ├── topic.py         # 话题检测
#       ├── memory_rank.py   # 记忆评分
#       ├── avatar.py        # 形象层（桌宠 dsh-pet）HTTP 适配
#       └── handler.py       # 主消息处理入口（组合上面四者）
#
# 完整设计说明见 docs/companion-features.md
# 形象层设计见 docs/avatar-integration.md
"""三体 AI 内容工作室 · 多智能体协作引擎（Grok 驱动）。"""

__version__ = "1.0.0"
__all__ = ["Studio", "Team", "Agent", "MeetingRoom", "MessageBus", "Blackboard", "get_llm"]

from .agents import Agent, Team
from .board import Blackboard
from .bus import MessageBus
from .llm import get_llm
from .meeting import MeetingRoom
from .workflow import Studio

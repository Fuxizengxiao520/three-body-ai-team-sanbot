"""员工档案与 Agent 行为：每个人有自己的系统提示、技能包、上下游和说话方式。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import skills
from .board import Blackboard
from .bus import MessageBus
from .llm import BaseLLM
from .models import Artifact, Task, now, uid

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "team.json"
TEAM_PRESETS: dict[str, Path] = {
    "trio": ROOT / "team-trio.json",   # 默认：三人精简编制
    "duo": ROOT / "team-duo.json",     # 两人极简编制
    "full": ROOT / "team.json",        # 七人完整编制
}
DEFAULT_TEAM = "trio"


def resolve_team_config(team: str | Path | None = None) -> Path:
    """把 --team 的值解析成配置文件路径；也接受自定义 json 路径。"""
    if team is None or team == "":
        return TEAM_PRESETS[DEFAULT_TEAM]
    if isinstance(team, Path):
        return team
    key = str(team).lower()
    if key in TEAM_PRESETS:
        return TEAM_PRESETS[key]
    p = Path(key).expanduser()
    if p.is_file():
        return p
    raise ValueError(f"未知编制 {team!r}，可选：{', '.join(TEAM_PRESETS)}，或一个团队配置 json 路径")


@dataclass
class Member:
    id: str
    name: str
    codename: str
    title: str
    mission: str
    principles: list[str] = field(default_factory=list)
    kpi: str = ""
    tools: list[str] = field(default_factory=list)
    upstream: list[str] = field(default_factory=list)
    downstream: list[str] = field(default_factory=list)
    voice: str = ""
    opens: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Member":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Team:
    def __init__(self, config_path: Path | str | None = None):
        path = Path(config_path) if config_path else DEFAULT_CONFIG
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.org = data["org"]
        self.version = data["version"]
        self.brain = data["brain"]
        self.moderator = data["meeting_moderator"]
        self.pipeline: list[str] = data["pipeline"]
        self.note = data.get("note", "")
        self.preset = data.get("preset", "custom")
        self.members: dict[str, Member] = {
            m["id"]: Member.from_dict(m) for m in data["members"]
        }
        missing = [mid for mid in self.pipeline if mid not in self.members]
        if missing:
            raise ValueError(f"团队配置有误：pipeline 中的 {missing} 不在 members 里")
        if self.moderator not in self.members:
            raise ValueError(f"团队配置有误：主持人 {self.moderator} 不在 members 里")

    def __getitem__(self, key: str) -> Member:
        return self.members[key]

    @property
    def size(self) -> int:
        return len(self.pipeline)

    @property
    def moderator_name(self) -> str:
        return self.name(self.moderator)

    def has(self, member_id: str) -> bool:
        return member_id in self.members

    def downstream_names(self, member_id: str) -> str:
        return "、".join(self.name(d) for d in self.members[member_id].downstream) or "（无，本棒为终点）"

    def name(self, member_id: str) -> str:
        return self.members[member_id].name if member_id in self.members else member_id

    def id_by_name(self, name: str) -> str | None:
        for mid, m in self.members.items():
            if m.name == name:
                return mid
        return None

    def roster_rows(self) -> list[dict]:
        rows = []
        for mid in self.pipeline:
            m = self.members[mid]
            rows.append(
                {
                    "角色": m.name,
                    "代号": m.codename,
                    "岗位": m.title,
                    "职责": m.mission,
                    "上游": " / ".join(self.name(u) for u in m.upstream) or "—",
                    "下游": " / ".join(self.name(d) for d in m.downstream) or "—",
                    "KPI": m.kpi,
                }
            )
        return rows


class Agent:
    """一名「员工」。会读收件箱、回执上游、干活、把活儿交给下一棒。"""

    def __init__(
        self,
        member: Member,
        team: Team,
        llm: BaseLLM,
        bus: MessageBus,
        board: Blackboard,
        run_dir: Path,
    ):
        self.m = member
        self.team = team
        self.llm = llm
        self.bus = bus
        self.board = board
        self.run_dir = Path(run_dir)
        self.artifact_dir = self.run_dir / "artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    @property
    def id(self) -> str:
        return self.m.id

    @property
    def name(self) -> str:
        return self.m.name

    def system_prompt(self, mode: str = "act") -> str:
        principles = "\n".join(f"- {p}" for p in self.m.principles)
        tools = ", ".join(self.m.tools)
        return (
            f"你是{self.m.name}，代号 {self.m.codename}，在「{self.team.org}」担任{self.m.title}。\n"
            f"职责：{self.m.mission}\n"
            f"你掌握的工具：{tools}\n"
            f"考核指标：{self.m.kpi}\n"
            f"行为准则：\n{principles}\n"
            f"说话风格：{self.m.voice}\n"
            "你和其他 AI 是同事，不是工具调用链：你可以追问、可以不同意、可以把活儿退回上游。\n"
            "用简体中文输出，Markdown 格式，只给交付物正文，不要解释你的思考过程。\n"
            "只能向在编名单里的同事派活或点名，不要提到名单外的人。\n\n"
            f"【在编名单】\n{'、'.join(self.team.name(mid) for mid in self.team.pipeline)}\n\n"
            f"【主持人】\n{self.team.moderator_name}\n\n"
            f"【我的下一棒】\n{self.team.downstream_names(self.m.id)}\n\n"
            f"【角色ID】\n{self.m.id}\n\n【模式】\n{mode}"
        )

    def _board_state(self) -> str:
        if not self.board.tasks:
            return "（看板为空）"
        lines = [f"- {t.id} [{t.status}] {t.title} → {self.team.name(t.owner)}" for t in self.board.tasks.values()]
        return "\n".join(lines)

    def _ack_upstream(self, task: Task) -> None:
        unread = self.bus.inbox(self.id, unread_only=True)
        self.bus.mark_read(self.id, unread)
        if unread:
            senders = "、".join(dict.fromkeys(self.team.name(m.sender) for m in unread if m.sender in self.team.members))
            targets = [m.sender for m in unread if m.sender in self.team.members]
            self.bus.send(
                self.id,
                targets or "@all",
                f"回执：{self.m.title}已接棒",
                f"收到 {len(unread)} 条交接（来自{senders or '统筹'}），任务卡 {task.id} 已置为进行中。"
                f"我按自己的准则复核后再往下递，有问题会直接找你。",
                kind="chat",
                task_id=task.id,
                in_reply_to=unread[-1].id,
            )

    def act(self, task: Task, brief: str, context: str = "") -> Artifact:
        self._ack_upstream(task)
        skill = skills.spec_for(self.id)
        spec = skill["spec"]
        upstream_text = context.strip()[:4000] or "（无上游材料，本次为生产线首棒）"
        prompt = (
            f"【本次任务】\n{brief}\n\n"
            f"【上游交接】\n{upstream_text}\n\n"
            f"【团队共享看板】\n{self._board_state()}\n\n"
            f"【输出要求】\n{spec}\n\n"
            "注意：交付物末尾请写清「交付人」与「下一棒」，便于下游接手。"
        )
        content = self.llm.complete(self.system_prompt("act"), prompt)
        fname = f"{len(list(self.artifact_dir.glob('*.md'))) + 1:02d}_{self.id}.md"
        path = self.artifact_dir / fname
        path.write_text(f"<!-- producer={self.id} task={task.id} -->\n\n{content}\n", encoding="utf-8")
        summary = next((ln.strip("# ").strip() for ln in content.splitlines() if ln.startswith("# ")), skill["title"])
        art = Artifact(
            id=uid("art"),
            title=skill["title"],
            path=str(path.relative_to(self.run_dir)),
            producer=self.id,
            task_id=task.id,
            summary=summary,
        )
        self.board.attach(task.id, art)

        # 交给下一棒（真正的 handoff，不是顺序调用函数）
        for nxt in self.m.downstream:
            self.bus.send(
                self.id,
                nxt,
                f"交接：{art.title} → 请接棒",
                f"{self.team.name(nxt)}，任务卡 {task.id} 已完成复核。\n"
                f"交付物：{art.path}\n要点：{summary}\n"
                "有异议直接回我，别往下硬传。",
                kind="handoff",
                task_id=task.id,
                attachments=[art.path],
            )
        # 向统筹汇报（维德自己不用汇报）
        if self.id != self.team.moderator:
            self.bus.send(
                self.id,
                self.team.moderator,
                f"进度：{self.m.title}已交付",
                f"{art.title} 已挂到看板 {task.id}，状态 review。",
                kind="report",
                task_id=task.id,
                attachments=[art.path],
            )
        return art

    def speak(self, topic: str) -> str:
        prompt = (
            f"【议题】\n{topic}\n\n"
            "【会议要求】\n以你的岗位立场发言，60 字以内，必须给出一个明确立场或动作建议，"
            "可以点名同事交接，不要复述别人的话，不要写标题。"
        )
        return self.llm.complete(self.system_prompt("speak"), prompt, temperature=0.9)

    def moderate(self, topic: str, transcript: str) -> str:
        prompt = (
            f"【议题】\n{topic}\n\n"
            f"【会议记录】\n{transcript[:6000]}\n\n"
            "【输出要求】\n你是主持人，汇总成一份决议：收敛分歧、给出 2-4 条可执行决议、"
            "每条标责任人与截止时间，最后一句收尾。不要复述全部发言。"
        )
        return self.llm.complete(self.system_prompt("moderate"), prompt, temperature=0.5)

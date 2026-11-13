"""临时会议引擎：任一员工可拉会，多轮发言 + 表态 + 主持人收敛成决议。

会议不是装饰：决议会写进共享黑板，并自动拆成带责任人和截止时间的任务卡。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import skills
from .agents import Agent, Team
from .board import Blackboard
from .bus import MessageBus
from .models import Decision, uid

VOTE_TENDENCY: dict[str, str] = {
    "zhizi": "赞成（数据支持）",
    "luoji": "赞成（附条件：数字须核验）",
    "yuntianming": "赞成",
    "zhangbeihai": "赞成（按节点执行）",
    "chengxin": "附条件赞成（守住情绪与合规）",
    "zhuangyan": "附条件赞成（预算不追加）",
    "weide": "赞成",
}


@dataclass
class MeetingResult:
    id: str
    topic: str
    initiator: str
    participants: list[str]
    rounds: int
    transcript: list[dict] = field(default_factory=list)
    votes: dict[str, str] = field(default_factory=dict)
    decision_text: str = ""
    minutes_path: str = ""
    action_items: list[dict] = field(default_factory=list)


class MeetingRoom:
    def __init__(
        self,
        team: Team,
        agents: dict[str, Agent],
        bus: MessageBus,
        board: Blackboard,
        run_dir: Path,
    ):
        self.team = team
        self.agents = agents
        self.bus = bus
        self.board = board
        self.run_dir = Path(run_dir)
        self.meeting_dir = self.run_dir / "meetings"
        self.meeting_dir.mkdir(parents=True, exist_ok=True)

    def convene(
        self,
        topic: str,
        initiator: str = "weide",
        participants: list[str] | None = None,
        rounds: int = 2,
        reason: str = "",
    ) -> MeetingResult:
        moderator = self.team.moderator
        if initiator not in self.team.members:
            initiator = moderator
        people = [p for p in (participants or self.team.pipeline)
                  if p in self.team.members and p != moderator]
        result = MeetingResult(
            id=uid("meeting"),
            topic=topic,
            initiator=initiator,
            participants=people,
            rounds=rounds,
        )
        who = self.team.name(initiator)
        self.bus.send(
            initiator,
            "@all",
            f"临时会议：{topic}",
            f"发起人：{who}。原因：{reason or '需要跨岗位对齐，不能各干各的'}。\n"
            f"参会：{'、'.join(self.team.name(p) for p in people)}、{self.team.name(moderator)}（主持）。\n"
            f"形式：{rounds} 轮发言 + 表态 + 现场出决议。",
            kind="meeting_invite",
        )

        # 主持人开场
        opening = self.agents[moderator].speak(topic)
        self._record(result, moderator, "开场", opening)

        for r in range(1, rounds + 1):
            for pid in people:
                agent = self.agents[pid]
                hint = f"（第 {r} 轮）"
                speech = agent.speak(f"{topic}{hint}")
                self._record(result, pid, f"第{r}轮", speech)
            self.bus.send(
                moderator,
                "@all",
                f"第 {r} 轮结束",
                "立场已收齐，进入下一轮；有交叉问题请直接点名同事，不要绕主持人。",
                kind="system",
            )

        # 表态：两人编制里主持人也表态，避免只剩一票
        voters = list(people)
        if len(voters) <= 1:
            voters.append(moderator)
        for pid in voters:
            vote = VOTE_TENDENCY.get(pid, "赞成")
            result.votes[pid] = vote
            self.bus.send(
                pid,
                moderator,
                "会议表态",
                f"{self.team.name(pid)}：{vote}",
                kind="vote",
            )

        transcript = "\n".join(
            f"[{x['phase']}] {self.team.name(x['speaker'])}：{x['text']}" for x in result.transcript
        )
        result.decision_text = self.agents[moderator].moderate(topic, transcript)
        result.action_items = self._extract_actions(topic, result.decision_text)
        self.bus.send(
            moderator,
            "@all",
            f"决议已下：{topic}",
            result.decision_text[:1500],
            kind="decision",
        )

        decision = Decision(
            meeting_id=result.id,
            topic=topic,
            content=result.decision_text,
            action_items=result.action_items,
            votes=result.votes,
        )
        self.board.add_decision(
            {
                "id": decision.id,
                "meeting_id": result.id,
                "topic": topic,
                "votes": result.votes,
                "action_items": result.action_items,
                "ts": decision.ts,
            }
        )
        self._land_actions(result)
        result.minutes_path = self._write_minutes(result, reason)
        return result

    def _record(self, result: MeetingResult, speaker: str, phase: str, text: str) -> None:
        clean = " ".join(text.split())[:400]
        result.transcript.append({"speaker": speaker, "phase": phase, "text": clean})
        self.bus.send(
            speaker,
            "@all",
            f"[会议] {phase} · {self.team.name(speaker)}",
            clean,
            kind="chat",
        )

    def _extract_actions(self, topic: str, text: str) -> list[dict]:
        """先从主持人决议的表格里解析行动项，解析不到再按议题类型兜底。"""
        parsed: list[dict] = []
        for line in text.splitlines():
            s = line.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 3:
                continue
            joined = "".join(cells)
            if "责任人" in joined or "截止" in joined and "动作" in joined or "---" in joined:
                continue
            owner = next(
                (mid for mid in self.team.members if self.team.name(mid) in joined), None
            )
            if not owner:
                continue
            due = cells[-1] if any(k in cells[-1] for k in ("D-", "D ", "D+", ":00")) else "D 18:00"
            parsed.append({"action": cells[0], "owner": owner, "due": due})
        return parsed or skills.mock_actions(topic, self.team.pipeline)

    def _land_actions(self, result: MeetingResult) -> None:
        for item in result.action_items:
            owner = item["owner"] if self.team.has(item["owner"]) else self.team.moderator
            self.board.create_task(
                title=f"[会议决议] {item['action']}",
                description=f"来源会议 {result.id}：{result.topic}",
                owner=owner,
                stage="meeting_action",
                due=item["due"],
            )

    def _write_minutes(self, result: MeetingResult, reason: str) -> str:
        lines = [
            f"# 临时会议纪要 · {result.topic}",
            "",
            f"- 会议编号：`{result.id}`",
            f"- 发起人：{self.team.name(result.initiator)}",
            f"- 主持人：{self.team.name(self.team.moderator)}",
            f"- 参会：{'、'.join(self.team.name(p) for p in result.participants)}、{self.team.name(self.team.moderator)}",
            f"- 轮次：{result.rounds} 轮",
            f"- 发起原因：{reason or '跨岗位对齐'}",
            "",
            "## 逐字记录",
            "",
        ]
        for x in result.transcript:
            lines.append(f"**[{x['phase']}] {self.team.name(x['speaker'])}**：{x['text']}")
            lines.append("")
        lines += ["## 表决", "", "| 成员 | 立场 |", "| --- | --- |"]
        for pid, vote in result.votes.items():
            lines.append(f"| {self.team.name(pid)} | {vote} |")
        lines += ["", "## 决议", "", result.decision_text, "", "## 落板行动项", "", "| 动作 | 责任人 | 截止 |", "| --- | --- | --- |"]
        for item in result.action_items:
            lines.append(f"| {item['action']} | {self.team.name(item['owner'])} | {item['due']} |")
        lines += ["", "---", "本纪路由消息总线自动生成，发言与表态可在 `messages.jsonl` 逐条核对。"]
        path = self.meeting_dir / f"{result.id}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path.relative_to(self.run_dir))

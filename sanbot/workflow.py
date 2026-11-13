"""制片厂：把在编员工接成一条会交接、会横向沟通、会临时开会的产线。

编制由 team 配置决定（默认三人），本模块不假设人数，也不假设具体谁在岗。"""
from __future__ import annotations

from pathlib import Path

from .agents import Agent, Team, resolve_team_config
from .board import Blackboard
from .bus import MessageBus
from .llm import get_llm
from .meeting import MeetingRoom, MeetingResult
from .models import Artifact, now

DEFAULT_BRIEF = "做一期 90 秒短视频：AI 智能体从工具变成同事，讲清楚多智能体协作怎么落地"


class Studio:
    def __init__(self, run_dir: Path | str, llm_mode: str | None = None,
                 config: Path | None = None, verbose: bool = True,
                 team: str | Path | None = None):
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        cfg = Path(config) if config else resolve_team_config(team)
        self.config_path = cfg
        self.team = Team(cfg)
        # 落一份编制快照，之后重新生成看板时能还原人名与岗位
        (self.run_dir / "team.json").write_text(cfg.read_text(encoding="utf-8"), encoding="utf-8")
        self.bus = MessageBus(self.run_dir)
        self.board = Blackboard(self.run_dir)
        self.llm = get_llm(llm_mode)
        self.agents: dict[str, Agent] = {
            mid: Agent(m, self.team, self.llm, self.bus, self.board, self.run_dir)
            for mid, m in self.team.members.items()
        }
        self.room = MeetingRoom(self.team, self.agents, self.bus, self.board, self.run_dir)
        self.verbose = verbose
        self.log_lines: list[str] = []

    def log(self, text: str) -> None:
        self.log_lines.append(text)
        if self.verbose:
            print(text, flush=True)

    # ---------------------------------------------------------------- 横向沟通
    def _full_roster(self) -> bool:
        return all(self.team.has(m) for m in
                   ("zhizi", "luoji", "yuntianming", "zhangbeihai",
                    "chengxin", "zhuangyan", "weide"))

    def _chatter(self, role_id: str, task_id: str) -> None:
        """产线之外的真实协作：追问、提醒、预警、越级汇报。收发双方必须在编。"""
        t = self.team
        has, mod = t.has, t.moderator
        if not self._full_roster():
            idx = t.pipeline.index(role_id)
            m = t[role_id]
            if idx > 0:
                prev = t.pipeline[idx - 1]
                self.bus.send(role_id, prev, f"横向复核：{m.title}对上游口径有疑问",
                              f"{t.name(prev)}，接你的材料时有一处要对齐：凡涉及数字、效能、"
                              "「完全自主」这类表述，我只按能核验的口径写，没出处的一律降级为推算。"
                              "有异议现在提，别等终审。",
                              kind="chat", task_id=task_id)
                self.bus.send(prev, role_id, "回复：口径按可核验执行",
                              "确认。来源清单随交付物一起给你，可直接引用；未核验的部分按推算标注，"
                              "谁引用谁负责。",
                              kind="chat", task_id=task_id)
            if role_id != mod:
                nxt = (m.downstream[0] if m.downstream and has(m.downstream[0]) else mod)
                self.bus.send(role_id, mod, f"进度预警：{m.title}已过自检",
                              f"{t.moderator_name}，这一棒自检完毕：素材缺口和引用风险都列进交付物了，"
                              f"{t.name(nxt)} 可以直接接手。节点若被挤压，按流程我现在就拉会，不拖到终审。",
                              kind="report", task_id=task_id)
            return

        if role_id == "luoji":
            self.bus.send("luoji", "zhizi", "交叉核验：标题边界要收窄",
                          "智子，你的立项建议里「AI 像真实员工」是比喻，写成完全自主会越界。请把标题收到可验证的动作上。",
                          kind="chat", task_id=task_id)
            self.bus.send("zhizi", "luoji", "回复：已收窄",
                          "确认。标题锚定「交接」这一个动作，其余表述交给你按来源清单把关。",
                          kind="chat", task_id=task_id)
        elif role_id == "yuntianming":
            self.bus.send("yuntianming", "chengxin", "提前求助：收尾会不会太满",
                          "程心，稿子第四段我留了 1.5 秒白，但怕整片情绪一路顶到底。你先替我看一眼，不等到审校环节。",
                          kind="chat", task_id=task_id)
            self.bus.send("chengxin", "yuntianming", "回复：留白保留，中段让一拍",
                          "留白别删。建议 00:48 那句后面给半秒，观众才接得住收尾。我会写进审校清单。",
                          kind="chat", task_id=task_id)
        elif role_id == "zhangbeihai":
            self.bus.send("zhangbeihai", "zhuangyan", "素材缺口报备：两处",
                          "庄颜，清单里两处素材缺口。按你的规矩先报账：能不能动备用金？不动我就用本地录屏顶上。",
                          kind="chat", task_id=task_id)
            self.bus.send("zhuangyan", "zhangbeihai", "回复：不动备用金",
                          "预算偏差已在 -5.9%，补拍会吃掉全部备用金。用现有录屏，节点不变，我记进台账。",
                          kind="chat", task_id=task_id)
        elif role_id == "chengxin":
            self.bus.send("chengxin", self.team.moderator, "合规预警：一票暂停权未启用",
                          "维德，三条风险均为非阻断，已给可执行修改清单。本轮不启用暂停权，可按节点推进。",
                          kind="report", task_id=task_id)
        elif role_id == "zhuangyan":
            self.bus.send("zhuangyan", self.team.moderator, "预算预警：未越线，但有行程风险",
                          "维德，偏差 -5.9%，无需追加。风险在排期：素材补齐与审校闭环只隔 3 小时，任一延误就压到终审。",
                          kind="report", task_id=task_id)

    # ---------------------------------------------------------------- 主流
    def run(self, brief: str = DEFAULT_BRIEF, meetings: int = 1, make_dashboard: bool = True) -> dict:
        t = self.team
        self.log(f"=== {t.org} 开工 ===")
        self.log(f"大脑：{self.llm.label}　|　运行目录：{self.run_dir}")
        self.log(f"任务：{brief}\n")

        self.bus.send(
            t.moderator, "@all", f"项目启动：{brief[:40]}",
            f"全线注意。本次目标：{brief}\n"
            "规则不变：上一棒做完自己交接，谁发现问题谁拉会，决议必须落板。前进。",
            kind="assign",
        )

        # 先把整条产线的任务卡铺到共享黑板上
        cards: dict[str, str] = {}
        for mid in t.pipeline:
            m = t[mid]
            card = self.board.create_task(
                title=f"{m.name} · {m.title}",
                description=brief,
                owner=mid,
                upstream=list(m.upstream),
                downstream=list(m.downstream),
                stage=mid,
            )
            cards[mid] = card.id

        seen_artifacts: list[Artifact] = []
        context = ""
        meeting_results: list[MeetingResult] = []

        for idx, mid in enumerate(t.pipeline, 1):
            m = t[mid]
            task_id = cards[mid]
            self.board.transition(task_id, "in_progress")
            self.log(f"[{idx}/{len(t.pipeline)}] {m.name}（{m.title}）接棒 …")

            if not m.upstream:
                self.bus.send(t.moderator, mid, f"派单：{m.title}",
                              f"{m.name}，第一棒给你。按你的准则筛，不达标的直接驳回，不用顾及进度。",
                              kind="assign", task_id=task_id)

            art = self.agents[mid].act(self.board.get(task_id), brief, context)
            seen_artifacts.append(art)
            self._chatter(mid, task_id)
            self.board.transition(task_id, "review")
            self.board.note(task_id, f"{m.name} 交付 {art.title}")
            self.board.transition(task_id, "done")
            self.log(f"    └ {art.title} → {art.path}")

            # 临时会议：完整编制按岗位事实冲突触发；精简编制按产线位置触发
            if self._full_roster():
                if meetings >= 1 and mid == "luoji":
                    self.log("    ⚡ 触发临时会议：事实边界与选题表述冲突")
                    mr = self.room.convene(
                        topic="立项对齐：标题边界与素材口径",
                        initiator="luoji",
                        rounds=2,
                        reason="罗辑发现「AI 像真实员工」存在事实越界风险，需要跨岗位当场收敛",
                    )
                    meeting_results.append(mr)
                    self.log(f"    └ 决议已落板：{mr.minutes_path}")
                if meetings >= 2 and mid == "zhuangyan":
                    self.log("    ⚡ 触发临时会议：排期挤压终审窗口")
                    mr = self.room.convene(
                        topic="预算与排期复核：素材补齐是否挤压终审",
                        initiator="zhuangyan",
                        rounds=1,
                        reason="素材补齐与审校闭环间隔仅 3 小时，需要当场定是否动备用金",
                    )
                    meeting_results.append(mr)
                    self.log(f"    └ 决议已落板：{mr.minutes_path}")
            else:
                triggers = []
                if meetings >= 1:
                    triggers.append((1, "口径对齐：事实边界与交付标准",
                                     "第一棒的事实口径与下游可执行标准需要当场收敛"))
                if meetings >= 2:
                    triggers.append((min(2, len(t.pipeline)),
                                     "预算与排期复核：素材补齐是否挤压终审",
                                     "素材补齐与终审窗口过近，需要当场定是否动备用金"))
                for at, topic, reason in triggers:
                    if idx != at:
                        continue
                    initiator = t.pipeline[at - 1]
                    self.log(f"    ⚡ 触发临时会议：{topic}")
                    mr = self.room.convene(topic=topic, initiator=initiator,
                                           rounds=2 if at == 1 else 1,
                                           reason=f"{t.name(initiator)} 交付后提出：{reason}")
                    meeting_results.append(mr)
                    self.log(f"    └ 决议已落板：{mr.minutes_path}")

            context = (self.run_dir / art.path).read_text(encoding="utf-8")
            if meeting_results:
                context += "\n\n【最新会议决议（必须遵守）】\n" + meeting_results[-1].decision_text

        self.bus.send(
            t.moderator, "@all", "全线收工：终审通过",
            f"{len(t.pipeline)} 棒全部交接完成，{len(seen_artifacts)} 份交付物挂板，"
            f"{len(meeting_results)} 次临时会议已形成决议。\n"
            "台账冻结，按决议执行。前进，散会。",
            kind="decision",
        )

        dashboard = ""
        if make_dashboard:
            from .render import render_dashboard
            dashboard = render_dashboard(self)

        summary = {
            "run_dir": str(self.run_dir),
            "brief": brief,
            "llm": self.llm.label,
            "team": {"preset": t.preset, "size": t.size,
                     "roster": [t.name(mid) for mid in t.pipeline]},
            "messages": len(self.bus),
            "tasks": self.board.summary(),
            "artifacts": len(seen_artifacts),
            "meetings": [m.minutes_path for m in meeting_results],
            "decisions": len(self.board.decisions),
            "dashboard": dashboard,
            "finished_at": now(),
        }
        self._write_summary(summary, seen_artifacts, meeting_results)
        self.log(f"\n=== 收工 ===\n消息 {summary['messages']} 条 / 交付物 {summary['artifacts']} 份 / "
                 f"会议 {len(meeting_results)} 次 / 决议 {summary['decisions']} 条")
        if dashboard:
            self.log(f"协作看板：{self.run_dir / dashboard}")
        return summary

    def hold_meeting(self, topic: str, initiator: str | None = None, rounds: int = 2) -> MeetingResult:
        initiator = initiator or self.team.moderator
        if not self.team.has(initiator):
            initiator = self.team.moderator
        return self.room.convene(topic, initiator=initiator, rounds=rounds,
                                 reason=f"{self.team.name(initiator)} 主动发起的临时协作会")

    def _write_summary(self, summary: dict, artifacts: list[Artifact], meetings: list[MeetingResult]) -> None:
        lines = [
            f"# 运行小结 · {summary['brief'][:40]}", "",
            f"- 大脑：{summary['llm']}",
            f"- 编制：{summary.get('team', {}).get('preset', 'custom')} · "
            f"{summary.get('team', {}).get('size', '?')} 人 → "
            f"{' → '.join(summary.get('team', {}).get('roster', []))}",
            f"- 内部消息：{summary['messages']} 条（全量见 `messages.jsonl`）",
            f"- 交付物：{summary['artifacts']} 份",
            f"- 临时会议：{len(meetings)} 次，决议 {summary['decisions']} 条",
            f"- 任务状态：{summary['tasks']}",
            "", "## 交付链", "",
        ]
        for i, a in enumerate(artifacts, 1):
            lines.append(f"{i}. **{self.team.name(a.producer)}** → [{a.title}]({a.path})")
        if meetings:
            lines += ["", "## 会议纪要", ""]
            lines += [f"- [{m.topic}]({m.minutes_path})（发起：{self.team.name(m.initiator)}）" for m in meetings]
        lines += ["", "## 怎么看这次协作", "",
                  "打开 `dashboard.html` 看全员沟通时间线；`board.json` 是共享黑板；",
                  "`messages.jsonl` 里每一条 handoff / chat / vote / decision 都可逐条回放。"]
        (self.run_dir / "run_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

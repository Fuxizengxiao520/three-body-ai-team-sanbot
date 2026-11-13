"""命令行入口：python -m sanbot <command>"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .intel import build_brief, fetch_headlines
from .llm import get_llm
from .render import render_dashboard
from .workflow import DEFAULT_BRIEF, Studio

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv() -> None:
    """把项目根 .env 读进环境变量；已存在的值优先，不覆盖 shell 里的设置。"""
    p = ROOT / ".env"
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def default_run_dir(tag: str = "run") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ROOT / "runs" / f"{stamp}-{tag}"


def resolve_dir(value: str | None, tag: str) -> Path:
    return Path(value) if value else default_run_dir(tag)


def print_roster(team) -> None:
    rows = team.roster_rows()
    print(f"\n{team.org} · 花名册（大脑：{team.brain}）")
    print(f"编制：{team.preset} · {team.size} 人" + (f"　|　{team.note}" if team.note else ""))
    print("=" * 96)
    for r in rows:
        print(f"{r['角色']:<5} {r['代号']:<14} {r['岗位']:<22} 上游：{r['上游']:<8} 下游：{r['下游']:<8}")
        print(f"      职责：{r['职责']}")
        print(f"      KPI：{r['KPI']}")
    print("=" * 96)
    print("流水线：" + " → ".join(team.name(m) for m in team.pipeline))


def cmd_run(args) -> int:
    studio = Studio(resolve_dir(args.run_dir, "run"), llm_mode=args.llm, team=args.team)
    s = studio.run(args.brief, meetings=args.meetings, make_dashboard=not args.no_dashboard)
    print("\n" + "-" * 60)
    print(json.dumps({k: v for k, v in s.items() if k != "finished_at"}, ensure_ascii=False, indent=2))
    return 0


def cmd_meeting(args) -> int:
    studio = Studio(resolve_dir(args.run_dir, "meeting"), llm_mode=args.llm, team=args.team)
    mr = studio.hold_meeting(args.topic, initiator=args.initiator, rounds=args.rounds)
    print(f"\n临时会议：{mr.topic}　发起：{studio.team.name(mr.initiator)}")
    print("-" * 60)
    for x in mr.transcript:
        print(f"[{x['phase']}] {studio.team.name(x['speaker'])}：{x['text']}")
    print("-" * 60)
    print(mr.decision_text)
    print(f"\n纪要：{studio.run_dir / mr.minutes_path}")
    render_dashboard(studio)
    return 0


def cmd_roster(args) -> int:
    from .agents import Team, resolve_team_config
    print_roster(Team(resolve_team_config(args.team)))
    return 0


def cmd_status(args) -> int:
    d = Path(args.run_dir) if args.run_dir else max(
        (p for p in (ROOT / "runs").glob("*") if p.is_dir() and (p / "board.json").exists()),
        key=lambda p: p.stat().st_mtime,
        default=None,
    )
    if not d or not (d / "board.json").exists():
        print("还没有运行记录，先执行：python -m sanbot run --mock")
        return 1
    data = json.loads((d / "board.json").read_text(encoding="utf-8"))
    print(f"看板：{d}")
    print(f"任务 {len(data['tasks'])} 张 / 交付物 {len(data['artifacts'])} 份 / 决议 {len(data.get('decisions', []))} 条")
    for t in data["tasks"]:
        print(f"  [{t['status']:<11}] {t['title']}  ← {len(t['artifacts'])} 份产物")
    p = d / "messages.jsonl"
    if p.exists():
        print(f"内部消息：{len(p.read_text(encoding='utf-8').splitlines())} 条")
    return 0


def cmd_dashboard(args) -> int:
    d = Path(args.run_dir)
    if not (d / "board.json").exists():
        print("该目录没有 board.json")
        return 1
    snapshot = d / "team.json"
    studio = Studio(d, llm_mode="mock", verbose=False,
                    team=str(snapshot) if snapshot.exists() else "trio")
    out = render_dashboard(studio)
    print(f"看板已生成：{d / out}")
    return 0


def cmd_intel(args) -> int:
    llm = get_llm(args.llm)
    print(f"资讯雷达正在抓取公开源（{llm.label}）…")
    items = fetch_headlines()
    print(f"抓到 {len(items)} 条\n")
    print(build_brief(items, llm))
    return 0


def cmd_issue(args) -> int:
    from .github_bot import handle_issue
    result = handle_issue(args.number, args.repo, args.token, args.run_root,
                          args.llm, args.command, args.team)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sanbot", description="三体 AI 内容工作室 · 多智能体协作引擎")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--run-dir", help="运行目录（默认 runs/<时间戳>-<命令>）")
        sp.add_argument("--llm", choices=["auto", "grok", "mock"], default="auto",
                        help="auto=有 XAI_API_KEY 就用 Grok，否则离线演示")
        sp.add_argument("--mock", action="store_true", help="快捷：强制离线演示（等同 --llm mock）")
        sp.add_argument("--grok", action="store_true", help="快捷：强制使用 Grok（等同 --llm grok）")
        sp.add_argument("--team", default=os.getenv("TEAM_PRESET") or "trio",
                        help="编制：trio 三人(默认) / duo 两人 / full 七人完整，或自定义团队 json 路径")

    r = sub.add_parser("run", help="跑完整产线")
    r.add_argument("--brief", default=DEFAULT_BRIEF, help="任务描述")
    r.add_argument("--meetings", type=int, default=1, choices=[0, 1, 2], help="自动临时会议次数")
    r.add_argument("--no-dashboard", action="store_true")
    add_common(r)
    r.set_defaults(func=cmd_run)

    m = sub.add_parser("meeting", help="临时拉一次会")
    m.add_argument("--topic", required=True)
    m.add_argument("--initiator", default=None,
                   help="发起人 id（默认主持人）；只能在当前在编名单里选")
    m.add_argument("--rounds", type=int, default=2)
    add_common(m)
    m.set_defaults(func=cmd_meeting)

    ro = sub.add_parser("roster", help="查看花名册")
    ro.add_argument("--team", default=os.getenv("TEAM_PRESET") or "trio", help="编制：trio / duo / full")
    ro.set_defaults(func=cmd_roster)

    st = sub.add_parser("status", help="查看最近一次看板")
    st.add_argument("--run-dir")
    st.set_defaults(func=cmd_status)

    da = sub.add_parser("dashboard", help="重新生成协作看板")
    da.add_argument("--run-dir", required=True)
    da.set_defaults(func=cmd_dashboard)

    it = sub.add_parser("intel", help="抓前沿资讯简报")
    it.add_argument("--llm", choices=["auto", "grok", "mock"], default="auto")
    it.set_defaults(func=cmd_intel)

    iss = sub.add_parser("issue", help="处理一个 GitHub Issue 里的 /team 命令")
    iss.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    iss.add_argument("--number", type=int, required=True)
    iss.add_argument("--token", default=os.getenv("GITHUB_TOKEN", ""))
    iss.add_argument("--run-root", default="runs")
    iss.add_argument("--command", default=os.getenv("TEAM_COMMAND", ""),
                     help="评论里的命令文本；不传则从 Issue 正文/标题解析")
    iss.add_argument("--llm", choices=["auto", "grok", "mock"], default="auto")
    iss.add_argument("--team", default=os.getenv("TEAM_PRESET") or "trio", help="编制：trio / duo / full")
    iss.set_defaults(func=cmd_issue)
    return p


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    if getattr(args, "mock", False):
        args.llm = "mock"
    elif getattr(args, "grok", False):
        args.llm = "grok"
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    except Exception as e:
        print(f"[错误] {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

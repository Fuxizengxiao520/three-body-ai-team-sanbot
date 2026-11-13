"""GitHub Issue 驱动的 bot：在 Issue 里下命令，团队在 CI 里干活并回帖。

支持命令（写在 Issue 正文或评论里）：
  /team run <任务描述>      跑完整产线
  /team meeting <议题>      临时开会
  /team intel               抓前沿资讯并开一份简报 Issue
  /team status              看板状态
  /team roster              花名册
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from .intel import build_brief, fetch_headlines
from .llm import get_llm
from .workflow import Studio

API = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str | None = None, repo: str | None = None):
        self.token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or ""
        self.repo = repo or os.getenv("GITHUB_REPOSITORY") or ""
        if not self.token:
            raise ValueError("缺少 GITHUB_TOKEN")
        if not self.repo:
            raise ValueError("缺少 repo（形如 owner/repo）或 GITHUB_REPOSITORY")

    def _api(self, path: str, method: str = "GET", payload: dict | None = None):
        url = path if path.startswith("http") else f"{API}/repos/{self.repo}/{path.lstrip('/')}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "three-body-ai-team/1.0",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"GitHub API {e.code}: {e.read().decode('utf-8', errors='replace')[:400]}") from e

    def get_issue(self, number: int) -> dict:
        return self._api(f"issues/{number}")

    def comment(self, number: int, body: str) -> dict:
        return self._api(f"issues/{number}/comments", "POST", {"body": body})

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict:
        return self._api("issues", "POST", {"title": title, "body": body, "labels": labels or []})

    def add_labels(self, number: int, labels: list[str]) -> dict:
        return self._api(f"issues/{number}/labels", "POST", {"labels": labels})

    def list_issues(self, state: str = "open", label: str = "") -> list[dict]:
        q = f"issues?state={state}&per_page=30"
        if label:
            q += f"&labels={urllib.parse.quote(label)}"
        return self._api(q)


def parse_command(text: str) -> tuple[str, str] | None:
    m = re.search(r"^/team\s+(\w+)\s*(.*)$", text or "", re.M | re.S)
    if not m:
        return None
    cmd = m.group(1).lower()
    arg = " ".join(m.group(2).split())[:1000]
    if cmd in {"run", "meeting", "intel", "status", "roster"}:
        return cmd, arg
    return None


def _run_dir(root: Path, tag: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(root) / f"{stamp}-{tag}"


def handle_issue(
    number: int,
    repo: str,
    token: str | None = None,
    root: str | Path = "runs",
    llm_mode: str | None = None,
    command_text: str | None = None,
    team: str | Path | None = None,
) -> dict:
    gh = GitHubClient(token, repo)
    issue = gh.get_issue(number)
    # 评论里的命令优先，其次 Issue 正文、标题
    parsed = (
        parse_command(command_text or "")
        or parse_command(issue.get("body") or "")
        or parse_command(issue.get("title") or "")
    )
    if not parsed:
        return {"ok": False, "reason": "Issue 中没有 /team 命令"}
    cmd, arg = parsed
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    studio = Studio(_run_dir(root, cmd), llm_mode=llm_mode, verbose=False, team=team)
    team = studio.team

    if cmd == "roster":
        rows = team.roster_rows()
        body = (f"## 三体 AI 团队 · 花名册\n\n> 编制：`{team.preset}` · {team.size} 人 · "
                f"{' → '.join(team.name(m) for m in team.pipeline)}\n\n"
                "| 角色 | 岗位 | 职责 | 上游 | 下游 |\n| --- | --- | --- | --- | --- |\n")
        body += "\n".join(
            f"| {r['角色']} | {r['岗位']} | {r['职责']} | {r['上游']} | {r['下游']} |" for r in rows
        )
    elif cmd == "status":
        body = f"## 看板状态\n\n```json\n{json.dumps(studio.board.summary(), ensure_ascii=False, indent=2)}\n```"
    elif cmd == "meeting":
        topic = arg or "跨岗位临时对齐"
        mr = studio.hold_meeting(topic, initiator=team.moderator, rounds=2)
        body = f"## 临时会议已结束：{topic}\n\n{mr.decision_text}\n\n> 完整逐字记录见本次运行的 `meetings/{Path(mr.minutes_path).name}`。"
    elif cmd == "intel":
        llm = get_llm(llm_mode)
        items = fetch_headlines()
        brief = build_brief(items, llm)
        created = gh.create_issue(
            f"[前沿情报] {datetime.now().strftime('%Y-%m-%d')} 前沿资讯简报",
            brief + f"\n\n---\n来源：arXiv cs.AI / Hacker News，抓取 {len(items)} 条。\n",
            ["team:intel"],
        )
        body = f"## 情报简报已发布\n\n{brief}\n\n新建 Issue：#{created.get('number')}"
    else:
        brief = arg or "做一期 90 秒短视频：AI 智能体从工具变成同事"
        summary = studio.run(brief, meetings=1)
        body = (
            f"## 全线交付完成：{brief}\n\n"
            f"- 大脑：`{summary['llm']}`\n"
            f"- 编制：`{summary['team']['preset']}` · {summary['team']['size']} 人"
            f"（{' → '.join(summary['team']['roster'])}）\n"
            f"- 内部沟通：**{summary['messages']} 条**（含交接、横向追问、表决、决议）\n"
            f"- 交付物：**{summary['artifacts']} 份**\n"
            f"- 临时会议：**{len(summary['meetings'])} 次**，决议 {summary['decisions']} 条\n"
            f"- 任务状态：`{summary['tasks']}`\n\n"
            "### 交付链\n\n" + "\n".join(
                f"{i}. {team.name(a.producer)} · {a.title}"
                for i, a in enumerate(sorted(studio.board.artifacts.values(), key=lambda x: x.ts), 1)
            ) + "\n\n> 运行产物（消息总线 / 黑板 / 看板 / 纪要）已写入 `runs/`，可由 CI 上传为 artifact。\n"
        )

    gh.comment(number, body[:65000])
    try:
        gh.add_labels(number, ["team:done"])
    except Exception:
        pass
    return {"ok": True, "cmd": cmd, "run_dir": str(studio.run_dir), "comment": body[:200]}

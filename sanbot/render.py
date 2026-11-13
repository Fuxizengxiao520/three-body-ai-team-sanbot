"""把内部沟通渲染成一张可离线打开的协作看板（纯 HTML，无外部依赖）。"""
from __future__ import annotations

import html
from pathlib import Path

KIND_LABEL = {
    "assign": ("派单", "#7aa2f7"),
    "handoff": ("交接", "#9ece6a"),
    "report": ("汇报", "#e0af68"),
    "chat": ("沟通", "#7dcfff"),
    "meeting_invite": ("拉会", "#bb9af7"),
    "vote": ("表决", "#ff9e64"),
    "decision": ("决议", "#f7768e"),
    "system": ("系统", "#565f89"),
}

STATUS_LABEL = {
    "backlog": "待办",
    "in_progress": "进行中",
    "review": "待复核",
    "done": "已完成",
    "blocked": "受阻",
}

AVATAR_COLOR = {
    "zhizi": "#7dcfff", "luoji": "#7aa2f7", "yuntianming": "#9ece6a",
    "zhangbeihai": "#e0af68", "chengxin": "#f7768e", "zhuangyan": "#bb9af7",
    "weide": "#ff9e64",
}


def e(s) -> str:
    return html.escape(str(s))


def render_dashboard(studio) -> str:
    team, bus, board = studio.team, studio.bus, studio.board
    run_dir = Path(studio.run_dir)
    msgs = bus.timeline()

    member_cards = []
    for mid in team.pipeline:
        m = team[mid]
        c = AVATAR_COLOR.get(mid, "#7aa2f7")
        member_cards.append(
            f'<div class="member"><div class="avatar" style="border-color:{c};color:{c}">{e(m.name[0])}</div>'
            f'<div class="mname">{e(m.name)}</div><div class="mrole">{e(m.title)}</div>'
            f'<div class="mtools">{e(" · ".join(m.tools))}</div></div>'
        )

    timeline = []
    for m in msgs:
        label, color = KIND_LABEL.get(m.kind, (m.kind, "#7aa2f7"))
        recipients = "、".join(team.name(r) if r in team.members else ("全员" if r == "@all" else r) for r in m.recipients)
        sender_name = team.name(m.sender) if m.sender in team.members else m.sender
        att = ""
        if m.attachments:
            att = '<div class="att">' + " ".join(
                f'<a href="{e(a)}">{e(Path(a).name)}</a>' for a in m.attachments
            ) + "</div>"
        timeline.append(
            f'<div class="msg"><div class="mhead"><span class="badge" style="background:{color}1f;color:{color};border-color:{color}66">{e(label)}</span>'
            f'<b>{e(sender_name)}</b><span class="arrow">→</span><span class="to">{e(recipients)}</span>'
            f'<span class="ts">{e(m.ts[11:19])}</span></div>'
            f'<div class="subject">{e(m.subject)}</div><pre class="body">{e(m.body)}</pre>{att}</div>'
        )

    cards = []
    for t in board.tasks.values():
        cards.append(
            f'<div class="task"><span class="st st-{e(t.status)}">{e(STATUS_LABEL.get(t.status, t.status))}</span>'
            f'<span class="tt">{e(t.title)}</span><span class="owner">{e(team.name(t.owner))}</span></div>'
        )

    meeting_files = sorted((run_dir / "meetings").glob("*.md")) if (run_dir / "meetings").exists() else []
    meeting_links = "".join(
        f'<li><a href="meetings/{e(p.name)}">{e(p.stem)}</a></li>' for p in meeting_files
    ) or "<li>本次未开会</li>"

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(team.org)} · 协作看板</title>
<style>
:root{{--bg:#11131a;--panel:#1a1d27;--panel2:#202432;--line:#2c3142;--fg:#d5dae8;--dim:#8b93a8;--accent:#7aa2f7}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:32px 24px 80px}}
h1{{font-size:26px;margin:0 0 6px}}h2{{font-size:17px;margin:36px 0 14px;padding-left:10px;border-left:3px solid var(--accent)}}
.sub{{color:var(--dim);font-size:13px}}
.stats{{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0 8px}}
.stat{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 18px;min-width:112px}}
.stat b{{display:block;font-size:22px;color:var(--accent)}}.stat span{{font-size:12px;color:var(--dim)}}
.members{{display:grid;grid-template-columns:repeat(auto-fill,minmax(144px,1fr));gap:10px}}
.member{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;text-align:center}}
.avatar{{width:38px;height:38px;line-height:36px;margin:0 auto 8px;border:2px solid;border-radius:50%;font-size:17px;font-weight:700}}
.mname{{font-weight:700}}.mrole{{font-size:12px;color:var(--fg);margin-top:2px}}.mtools{{font-size:11px;color:var(--dim);margin-top:6px}}
.grid{{display:grid;grid-template-columns:1.55fr 1fr;gap:18px}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
.msg{{background:var(--panel);border:1px solid var(--line);border-left:2px solid #39405a;border-radius:8px;padding:11px 14px;margin-bottom:9px}}
.mhead{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px}}
.badge{{border:1px solid;border-radius:4px;padding:0 7px;font-size:11px}}
.arrow,.ts{{color:var(--dim)}}.ts{{margin-left:auto;font-variant-numeric:tabular-nums}}.to{{color:var(--dim)}}
.subject{{font-weight:600;margin-top:6px;font-size:13px}}
.body{{white-space:pre-wrap;word-break:break-word;margin:6px 0 0;font:12px/1.65 inherit;color:#b9c0d4;max-height:190px;overflow:auto}}
.att a{{color:var(--accent);font-size:11px;margin-right:8px;text-decoration:none}}
.task{{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:8px 10px;margin-bottom:7px;font-size:12px}}
.st{{border-radius:4px;padding:1px 7px;font-size:11px;background:#2b3040;color:#a9b1c6;white-space:nowrap}}
.st-done{{background:#1d3a2a;color:#9ece6a}}.st-in_progress{{background:#22304a;color:#7aa2f7}}.st-review{{background:#3a3220;color:#e0af68}}
.tt{{flex:1}}.owner{{color:var(--dim)}}
.box{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 18px;max-height:640px;overflow:auto}}
a{{color:var(--accent)}}li{{margin:4px 0;font-size:12px}}
footer{{margin-top:40px;color:var(--dim);font-size:11px;text-align:center}}
</style></head><body><div class="wrap">
<h1>{e(team.org)} · 内部协作看板</h1>
<div class="sub">大脑 {e(studio.llm.label)}　|　运行目录 {e(run_dir.name)}　|　全部沟通真实落盘于 messages.jsonl</div>
<div class="stats">
<div class="stat"><b>{len(msgs)}</b><span>内部消息</span></div>
<div class="stat"><b>{len(board.tasks)}</b><span>任务卡</span></div>
<div class="stat"><b>{len(board.artifacts)}</b><span>交付物</span></div>
<div class="stat"><b>{len(board.decisions)}</b><span>会议决议</span></div>
<div class="stat"><b>{len(team.pipeline)}</b><span>在岗员工</span></div>
</div>
<h2>在岗花名册</h2><div class="members">{''.join(member_cards)}</div>
<div class="grid">
<div><h2>内部沟通时间线</h2><div class="box">{''.join(timeline)}</div></div>
<div><h2>共享黑板</h2><div class="box">{''.join(cards)}</div>
<h2>临时会议纪要</h2><div class="box"><ul>{meeting_links}</ul></div>
<h2>交付链</h2><div class="box"><ul>{''.join(f'<li>{e(team.name(a.producer))} · <a href="{e(a.path)}">{e(a.title)}</a></li>' for a in sorted(board.artifacts.values(), key=lambda x: x.ts))}</ul></div>
</div></div>
<footer>三体 AI 内容工作室 · 消息总线 / 共享黑板 / 临时会议引擎 · 本页可离线打开</footer>
</div></body></html>"""
    out = run_dir / "dashboard.html"
    out.write_text(html_doc, encoding="utf-8")
    return out.name

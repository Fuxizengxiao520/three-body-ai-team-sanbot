"""罗辑的资讯雷达：抓公开源（arXiv cs.AI / Hacker News），失败自动降级不阻断产线。"""
from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from .llm import BaseLLM

UA = "three-body-ai-team/1.0 (+github bot)"
ARXIV_RSS = "https://export.arxiv.org/rss/cs.AI"
HN_API = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=12"


def _get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_headlines(limit: int = 8) -> list[dict]:
    items: list[dict] = []
    try:
        root = ET.fromstring(_get(ARXIV_RSS))
        for it in root.iter("item"):
            items.append({
                "source": "arXiv cs.AI",
                "title": (it.findtext("title") or "").strip().replace("\n", " "),
                "url": (it.findtext("link") or "").strip(),
            })
            if len(items) >= limit // 2:
                break
    except Exception:
        pass
    try:
        data = json.loads(_get(HN_API).decode("utf-8"))
        for h in data.get("hits", []):
            items.append({
                "source": "Hacker News",
                "title": h.get("title") or "",
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            })
            if len(items) >= limit:
                break
    except Exception:
        pass
    return items[:limit]


def build_brief(headlines: list[dict], llm: BaseLLM, focus: str = "AI 智能体 / 多智能体协作") -> str:
    if not headlines:
        return (
            f"# 罗辑 · 前沿资讯简报（{datetime.now().strftime('%Y-%m-%d')}）\n\n"
            f"> 关注方向：{focus}\n\n"
            "**本期未取到外部源**（网络不可达或源站限流），按流程降级：不编造条目，"
            "仅提示本次资讯缺口，待下一次任务重试。\n"
        )
    listing = "\n".join(f"{i}. [{h['source']}] {h['title']} — {h['url']}" for i, h in enumerate(headlines, 1))
    prompt = (
        f"【本次任务】\n整理今日 {focus} 方向的前沿资讯简报\n\n"
        f"【原始条目】\n{listing}\n\n"
        "【输出要求】\n从上面条目里挑出与「AI 从工具走向协作体」最相关的 3-5 条，"
        "每条写一句中文解读（说明了什么趋势），最后给一句给内容团队的选题提示。"
        "不确定的地方标注「待核验」，不要编造原文里没有的数字。用 Markdown。"
    )
    if llm.is_mock:
        keywords = ("agent", "ai", "llm", "model", "gpt", "claude", "grok", "gemini",
                    "openai", "anthropic", "智能体", "模型", "推理", "copilot", "autonomous")
        hits = [h for h in headlines if any(k in h["title"].lower() for k in keywords)]
        if hits:
            picked = "\n".join(
                f"- **{h['title']}**（{h['source']}）：关键词命中，列为候选选题锚点。"
                f"**未经语义核验，禁止直接引用**。{h['url']}"
                for h in hits[:4]
            )
            verdict = f"关键词粗筛命中 {len(hits)} 条，其余 {len(headlines) - len(hits)} 条判定为弱相关，不做牵强关联。"
        else:
            picked = "\n".join(f"- {h['title']}（{h['source']}）：弱相关，仅存档。{h['url']}" for h in headlines[:4])
            verdict = "本次抓到的条目与关注方向无明显重合，**不编造关联**，建议改抓专用源或等下一轮。"
        return (
            f"# 罗辑 · 前沿资讯简报（{datetime.now().strftime('%Y-%m-%d')}）\n\n"
            f"> 关注方向：{focus}　|　抓到 {len(headlines)} 条　|　离线演示模式（仅关键词粗筛）\n\n"
            f"**核验结论**：{verdict}\n\n## 候选条目\n\n{picked}\n\n"
            "**选题提示**：优先做「交接 / 共享状态 / 临时决策」这类能演示的过程，"
            "别再做工具盘点。所有结论需接 Grok 后重新核验。\n"
        )
    return llm.complete("你是罗辑，负责前沿资讯与事实核验。只认可交叉验证的信息，区分事实与推算。", prompt, temperature=0.4)

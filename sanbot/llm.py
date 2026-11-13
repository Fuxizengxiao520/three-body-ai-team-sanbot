"""Grok (xAI) 后端 + 无密钥演示后端。

真实模式走 xAI 的 OpenAI 兼容接口；没有 XAI_API_KEY 时自动降级为本地
MockLLM，整条协作链、交接、开会、看板依然能完整跑通，方便先验收再配密钥。
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from . import skills

DEFAULT_ENDPOINT = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-4-fast"


class BaseLLM:
    is_mock = False
    label = "base"

    def complete(self, system: str, prompt: str, temperature: float = 0.7) -> str:  # pragma: no cover
        raise NotImplementedError


class GrokClient(BaseLLM):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str | None = None,
        timeout: int = 120,
    ):
        self.api_key = api_key or os.getenv("XAI_API_KEY", "")
        self.model = model or os.getenv("GROK_MODEL", DEFAULT_MODEL)
        self.endpoint = endpoint or os.getenv("XAI_BASE_URL", DEFAULT_ENDPOINT).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("缺少 XAI_API_KEY，请在 .env 中配置或改用 mock 模式")
        self.label = f"Grok ({self.model})"

    def complete(self, system: str, prompt: str, temperature: float = 0.7) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "stream": False,
        }
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "three-body-ai-team/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Grok API {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"Grok API 连接失败: {e}") from e


class MockLLM(BaseLLM):
    """离线演示大脑：按岗位产出结构化交付物，不联网、不花钱。"""

    is_mock = True
    label = "Mock (离线演示)"

    @staticmethod
    def _tag(text: str, name: str) -> str:
        m = re.search(rf"【{name}】\s*\n(.*?)(?=\n\n【|\Z)", text, re.S)
        return m.group(1).strip() if m else ""

    def complete(self, system: str, prompt: str, temperature: float = 0.7) -> str:
        role_id = self._tag(system, "角色ID") or "weide"
        mode = self._tag(system, "模式") or "act"
        brief = self._tag(prompt, "本次任务")
        context = self._tag(prompt, "上游交接")
        names = self._tag(system, "在编名单")
        roster = ([rid for rid, n in skills.ROLE_NAMES.items() if n in names]
                  if names else None)
        moderator = self._tag(system, "主持人") or None
        next_name = self._tag(system, "我的下一棒") or None
        if mode == "speak":
            topic = self._tag(prompt, "议题") or brief
            return skills.render_mock_speech(role_id, topic, roster)
        if mode == "moderate":
            topic = self._tag(prompt, "议题") or brief
            transcript = self._tag(prompt, "会议记录")
            return skills.render_mock_decision(topic, transcript, roster, moderator)
        return skills.render_mock_deliverable(role_id, brief, context, roster, next_name)


def get_llm(mode: str | None = None) -> BaseLLM:
    """mode: auto(默认，有 key 用 Grok) | grok | mock"""
    mode = (mode or os.getenv("SANBOT_LLM", "auto")).lower()
    if mode == "mock":
        return MockLLM()
    if mode == "grok":
        return GrokClient()
    if os.getenv("XAI_API_KEY"):
        return GrokClient()
    return MockLLM()

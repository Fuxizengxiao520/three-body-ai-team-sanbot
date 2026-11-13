"""内部消息总线：所有员工沟通都经过这里，全程留痕、可回放。"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Message


class MessageBus:
    """支持定向、广播、回执与未读收件箱的消息总线。

    消息以 JSONL 全量落盘（单人工作室规模下足够），重启后可完整恢复现场。
    """

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "messages.jsonl"
        self.messages: list[Message] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.messages.append(Message.from_dict(json.loads(line)))

    def publish(self, msg: Message) -> Message:
        self.messages.append(msg)
        self._flush()
        return msg

    def send(
        self,
        sender: str,
        recipients: list[str] | str,
        subject: str,
        body: str,
        kind: str = "chat",
        task_id: str | None = None,
        attachments: list[str] | None = None,
        in_reply_to: str | None = None,
    ) -> Message:
        return self.publish(
            Message(
                sender=sender,
                recipients=[recipients] if isinstance(recipients, str) else list(recipients),
                kind=kind,
                subject=subject,
                body=body,
                task_id=task_id,
                attachments=attachments or [],
                in_reply_to=in_reply_to,
            )
        )

    def _flush(self) -> None:
        text = "\n".join(m.to_json() for m in self.messages) + "\n"
        self.path.write_text(text, encoding="utf-8")

    def _visible(self, msg: Message, agent: str) -> bool:
        return msg.sender == agent or "@all" in msg.recipients or agent in msg.recipients

    def inbox(self, agent: str, unread_only: bool = True) -> list[Message]:
        out = []
        for m in self.messages:
            if not self._visible(m, agent):
                continue
            if unread_only and (agent in m.read_by or m.sender == agent):
                continue
            out.append(m)
        return out

    def mark_read(self, agent: str, messages: list[Message]) -> None:
        ids = {m.id for m in messages}
        changed = False
        for m in self.messages:
            if m.id in ids and agent not in m.read_by:
                m.read_by.append(agent)
                changed = True
        if changed:
            self._flush()

    def timeline(self, limit: int | None = None) -> list[Message]:
        return self.messages[-limit:] if limit else list(self.messages)

    def by_kind(self, kind: str) -> list[Message]:
        return [m for m in self.messages if m.kind == kind]

    def __len__(self) -> int:
        return len(self.messages)

"""共享黑板：任务状态机 + 产出物登记。所有人对同一张板子读写。"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Artifact, Task, now


class Blackboard:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "board.json"
        self.tasks: dict[str, Task] = {}
        self.artifacts: dict[str, Artifact] = {}
        self.decisions: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        for d in data.get("tasks", []):
            t = Task(**{k: v for k, v in d.items() if k in Task.__dataclass_fields__})
            self.tasks[t.id] = t
        for d in data.get("artifacts", []):
            a = Artifact(**{k: v for k, v in d.items() if k in Artifact.__dataclass_fields__})
            self.artifacts[a.id] = a
        self.decisions = data.get("decisions", [])

    def save(self) -> None:
        payload = {
            "updated_at": now(),
            "tasks": [vars(t) for t in self.tasks.values()],
            "artifacts": [vars(a) for a in self.artifacts.values()],
            "decisions": self.decisions,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def create_task(self, **kwargs) -> Task:
        t = Task(**kwargs)
        self.tasks[t.id] = t
        self.save()
        return t

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def transition(self, task_id: str, status: str) -> bool:
        t = self.tasks.get(task_id)
        if not t or not t.transition(status):
            return False
        self.save()
        return True

    def attach(self, task_id: str, artifact: Artifact) -> None:
        self.artifacts[artifact.id] = artifact
        t = self.tasks.get(task_id)
        if t and artifact.path not in t.artifacts:
            t.artifacts.append(artifact.path)
            t.updated_at = now()
        self.save()

    def note(self, task_id: str, text: str) -> None:
        t = self.tasks.get(task_id)
        if t:
            t.notes.append(f"[{now()}] {text}")
            self.save()

    def add_decision(self, decision: dict) -> None:
        self.decisions.append(decision)
        self.save()

    def latest_artifact(self, producer: str | None = None) -> Artifact | None:
        items = [a for a in self.artifacts.values() if producer is None or a.producer == producer]
        return sorted(items, key=lambda a: a.ts)[-1] if items else None

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.tasks.values():
            out[t.status] = out.get(t.status, 0) + 1
        return out

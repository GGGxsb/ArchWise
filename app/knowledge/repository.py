from __future__ import annotations

import json
from pathlib import Path

from app.knowledge.styles import load_default_styles
from app.models.schemas import ArchitectureStyle, CaseRequest


class KnowledgeRepository:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path("data")
        self.styles_file = self.data_dir / "custom_styles.json"
        self.cases_file = self.data_dir / "learned_cases.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def list_styles(self) -> list[ArchitectureStyle]:
        styles = {style.id: style for style in load_default_styles()}
        for style in self._load_custom_styles():
            styles[style.id] = style
        return list(styles.values())

    def add_style(self, style: ArchitectureStyle) -> ArchitectureStyle:
        styles = {item.id: item for item in self._load_custom_styles()}
        styles[style.id] = style
        self._write_json(self.styles_file, [item.model_dump() for item in styles.values()])
        return style

    def list_cases(self) -> list[CaseRequest]:
        if not self.cases_file.exists():
            return []
        payload = json.loads(self.cases_file.read_text(encoding="utf-8"))
        return [CaseRequest(**item) for item in payload]

    def add_case(self, case: CaseRequest) -> CaseRequest:
        cases = self.list_cases()
        cases.append(case)
        self._write_json(self.cases_file, [item.model_dump() for item in cases])
        return case

    def _load_custom_styles(self) -> list[ArchitectureStyle]:
        if not self.styles_file.exists():
            return []
        payload = json.loads(self.styles_file.read_text(encoding="utf-8"))
        return [ArchitectureStyle(**item) for item in payload]

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

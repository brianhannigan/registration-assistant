import json
from pathlib import Path
from typing import Dict, Any

class MappingStore:
    def __init__(self, base_dir: str = "mappings"):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def _path_for_domain(self, domain: str) -> Path:
        safe = domain.replace(":", "_").replace("/", "_")
        return self.base / f"{safe}.json"

    def load(self, domain: str) -> Dict[str, Any]:
        p = self._path_for_domain(domain)
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, domain: str, data: Dict[str, Any]) -> None:
        p = self._path_for_domain(domain)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")

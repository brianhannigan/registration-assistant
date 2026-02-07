from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class RegistrantProfile:
    registrant_name: str = ""
    email: str = ""
    phone: str = ""
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""

@dataclass
class PageField:
    label_hint: str
    tag: str
    input_type: str
    name: str
    id: str
    placeholder: str
    aria_label: str
    role: str
    selector: str
    confidence: float = 0.0

@dataclass
class WorkflowConfig:
    url: str = ""
    field_bindings: Dict[str, str] = field(default_factory=dict)
    session_bindings: Dict[str, str] = field(default_factory=dict)
    continue_selector: Optional[str] = None

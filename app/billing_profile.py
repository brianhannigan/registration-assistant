from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any, Dict

# NOTE: This module intentionally excludes payment card data (PAN/CVV/expiry).
# It is for non-sensitive billing/contact details only.

FORBIDDEN_KEYS = {
    "pan","card_number","number","cc_number","ccnum",
    "cvv","cvc","security_code",
    "exp","expiry","expiration","exp_month","exp_year","mm","yy"
}

@dataclass
class BillingProfile:
    profile_name: str = "Default Billing"
    billing_name: str = ""
    email: str = ""
    phone: str = ""
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "US"
    name_on_card: str = ""   # allowed (not sensitive by itself)
    card_last4: str = ""     # allowed (display-only)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "BillingProfile":
        bp = BillingProfile()
        for k, v in (d or {}).items():
            if k.lower() in FORBIDDEN_KEYS:
                continue
            if hasattr(bp, k):
                setattr(bp, k, v if v is not None else "")
        return bp

def load_billing_profile(path: str) -> BillingProfile:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Billing JSON must be an object/dict.")
    return BillingProfile.from_dict(data)

def save_billing_profile(path: str, profile: BillingProfile) -> None:
    p = Path(path)
    p.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")

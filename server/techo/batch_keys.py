import hashlib
import json


def source_key(value: str) -> str:
    return "source:" + hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def content_key(kind: str, values: dict) -> str:
    fields = (
        ("scope", "period", "text") if kind == "goal" else ("date", "text" if kind == "note" else "title")
    )
    identity = {field: values[field].strip() for field in fields}
    identity["type"] = kind
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "content:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

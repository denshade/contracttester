"""Verification triggers are http(s) URLs called with an optional token and headers."""

import json
from urllib.parse import urlsplit

_MAX_HEADERS = 20


def clean_http_url(value: str, label: str = "Verification trigger", max_length: int = 2000) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if len(cleaned) > max_length:
        raise ValueError(f"{label} must be at most {max_length} characters")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must be an http or https URL")
    return cleaned


def clean_token(value: str, max_length: int = 500) -> str:
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise ValueError(f"Token must be at most {max_length} characters")
    if "\n" in cleaned or "\r" in cleaned:
        raise ValueError("Token must be a single line")
    return cleaned


def clean_header_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("Header name is required")
    if len(name) > 100:
        raise ValueError("Header name must be at most 100 characters")
    if any(character.isspace() or character == ":" for character in name):
        raise ValueError("Header name cannot contain spaces")
    return name


def clean_header_value(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > 500:
        raise ValueError("Header value must be at most 500 characters")
    if "\n" in cleaned or "\r" in cleaned:
        raise ValueError("Header value must be a single line")
    return cleaned


def clean_header_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if len(pairs) > _MAX_HEADERS:
        raise ValueError(f"A verifier can have at most {_MAX_HEADERS} headers")
    cleaned: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, header_value in pairs:
        header_name = clean_header_name(name)
        key = header_name.casefold()
        if key in seen:
            raise ValueError(f"Header {header_name} is listed more than once")
        seen.add(key)
        cleaned.append((header_name, clean_header_value(header_value)))
    return cleaned


def parse_header_block(value: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError("Each header must look like Name: Value")
        name, _, header_value = line.partition(":")
        pairs.append((name, header_value))
    return clean_header_pairs(pairs)


def format_headers(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{name}: {value}" for name, value in pairs)


def dump_headers(pairs: list[tuple[str, str]]) -> str:
    return json.dumps([{"name": name, "value": value} for name, value in pairs], separators=(",", ":"))


def load_headers(raw: str | None) -> list[tuple[str, str]]:
    if not raw or raw == "[]":
        return []
    data = json.loads(raw)
    return [(str(item["name"]), str(item["value"])) for item in data]

"""HTTP verbs a statement can use."""

HTTP_VERBS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


def clean_verb(value: str) -> str:
    cleaned = value.strip().upper()
    if cleaned not in HTTP_VERBS:
        allowed = ", ".join(HTTP_VERBS)
        raise ValueError(f"Verb must be one of {allowed}")
    return cleaned

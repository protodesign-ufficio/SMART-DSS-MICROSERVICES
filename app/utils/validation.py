def ensure_positive(value: int, name: str):
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value

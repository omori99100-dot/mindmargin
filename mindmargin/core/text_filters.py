def is_on_niche(topic: str) -> bool:
    if not topic or "#" in topic:
        return False
    letters = [c for c in topic if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if c.isascii())
    return latin / len(letters) >= 0.8
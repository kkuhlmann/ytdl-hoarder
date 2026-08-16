def page_count(total: int, page_size: int | None) -> int:
    """Pages needed for `total` rows; no/zero page_size means one unpaginated page."""
    if not page_size:
        return 1
    return (total + page_size - 1) // page_size

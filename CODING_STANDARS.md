# CODING_STANDARS

- For object references in Python (`window`, `handler`, `callback`, `manager`, `lock`, widgets, regex match objects), use truthy checks: `if obj` / `if not obj`.
- Do not use `is None` / `is not None` for those object references.
- Keep explicit `is None` / `is not None` for scalar optionals where `None` is a real value state (`int`, `str`, addresses, row indexes, sizes, flags), or where empty value is semantically different from `None`.
- Do not repeat (DRY)
- Keep it simple (KISS)
- Apply proper separation of concers
- Respect classes reponsibility

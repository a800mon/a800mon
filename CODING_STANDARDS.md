# CODING_STANDARDS

- Zero bloat is mandatory.
- Do not add redundant coercions or wrappers (`bool(...)`, `int(...)`, `str(...)`) when type is already guaranteed by API/type hints.
- Do not add forwarding helpers that only pass through parameters without adding behavior.
- For object references in Python (`window`, `handler`, `callback`, manager/widget/lock objects), use truthy checks: `if obj` / `if not obj`.
- Keep explicit `is None` / `is not None` only for scalar optionals where `None` is a distinct value state (`int`, `str`, addresses, indexes, sizes, flags), or where empty value differs semantically from `None`.
- Keep explicit coercion only at real boundaries (RPC payload decode, CLI/raw input, external library return types).
- DRY and KISS are required.
- Python import order must follow `isort`.
- Python formatting must follow `black` style.
- Go formatting must follow `gofmt` (and `goimports` when imports change).
- Do not commit code that fails formatter checks for its language.

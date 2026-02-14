class Trainer:
    def __init__(self, start: int, end: int, value: int | None = None):
        self.start_addr = start & 0xFFFF
        self.end_addr = end & 0xFFFF
        self.length = (self.end_addr - self.start_addr) + 1
        self.value = None if value is None else (value & 0xFF)
        self.snapshot = b""
        self.candidates = []
        self._reader = None

    def bind_reader(self, reader):
        self._reader = reader

    def start(self, value: int | None = None):
        if value is not None:
            self.value = value & 0xFF
        if self.value is None:
            raise ValueError("Missing trainer start value.")
        current = self._read()
        self.snapshot = current
        target = self.value
        self.candidates = [idx for idx, b in enumerate(current) if b == target]
        return len(self.candidates)

    def changed(self, value: int):
        current = self._read()
        target = value & 0xFF
        self.candidates = [
            idx
            for idx in self.candidates
            if current[idx] != self.snapshot[idx] and current[idx] == target
        ]
        self.snapshot = current
        self.value = target
        return len(self.candidates)

    def not_changed(self):
        current = self._read()
        self.candidates = [
            idx for idx in self.candidates if current[idx] == self.snapshot[idx]
        ]
        self.snapshot = current
        return len(self.candidates)

    def reset(self):
        self.snapshot = b""
        self.candidates = []

    def rows(self, limit: int | None = None):
        total = len(self.candidates)
        shown = total if limit is None or limit > total else limit
        return [
            ((self.start_addr + offset) & 0xFFFF, self.snapshot[offset])
            for offset in self.candidates[:shown]
        ]

    def _read(self):
        if not self._reader:
            raise RuntimeError("Trainer reader is not bound.")
        return self._reader(self.start_addr, self.length)

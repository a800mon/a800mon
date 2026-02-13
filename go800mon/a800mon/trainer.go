package a800mon

import "errors"

type Trainer struct {
	startAddr  uint16
	endAddr    uint16
	length     int
	value      byte
	hasValue   bool
	snapshot   []byte
	candidates []int
	reader     func(start uint16, length int) ([]byte, error)
}

type TrainerRow struct {
	Addr  uint16
	Value byte
}

func NewTrainer(start uint16, end uint16, value *byte) (*Trainer, error) {
	if end < start {
		return nil, errors.New("Stop address must be >= start address.")
	}
	t := &Trainer{
		startAddr: start,
		endAddr:   end,
		length:    int(end-start) + 1,
	}
	if value != nil {
		t.value = *value
		t.hasValue = true
	}
	return t, nil
}

func (t *Trainer) BindReader(reader func(start uint16, length int) ([]byte, error)) {
	t.reader = reader
}

func (t *Trainer) Start(value *byte) (int, error) {
	if value != nil {
		t.value = *value
		t.hasValue = true
	}
	if !t.hasValue {
		return 0, errors.New("Missing trainer start value.")
	}
	current, err := t.read()
	if err != nil {
		return 0, err
	}
	t.snapshot = current
	t.candidates = t.candidates[:0]
	target := t.value
	for idx, b := range current {
		if b == target {
			t.candidates = append(t.candidates, idx)
		}
	}
	return len(t.candidates), nil
}

func (t *Trainer) Changed(value byte) (int, error) {
	current, err := t.read()
	if err != nil {
		return 0, err
	}
	next := make([]int, 0, len(t.candidates))
	for _, idx := range t.candidates {
		if current[idx] != t.snapshot[idx] && current[idx] == value {
			next = append(next, idx)
		}
	}
	t.candidates = next
	t.snapshot = current
	t.value = value
	t.hasValue = true
	return len(t.candidates), nil
}

func (t *Trainer) NotChanged() (int, error) {
	current, err := t.read()
	if err != nil {
		return 0, err
	}
	next := make([]int, 0, len(t.candidates))
	for _, idx := range t.candidates {
		if current[idx] == t.snapshot[idx] {
			next = append(next, idx)
		}
	}
	t.candidates = next
	t.snapshot = current
	return len(t.candidates), nil
}

func (t *Trainer) Reset() {
	t.snapshot = nil
	t.candidates = nil
}

func (t *Trainer) MatchCount() int {
	return len(t.candidates)
}

func (t *Trainer) Rows(limit int) []TrainerRow {
	total := len(t.candidates)
	if limit <= 0 || limit > total {
		limit = total
	}
	rows := make([]TrainerRow, 0, limit)
	for _, idx := range t.candidates[:limit] {
		rows = append(rows, TrainerRow{
			Addr:  uint16((int(t.startAddr) + idx) & 0xFFFF),
			Value: t.snapshot[idx],
		})
	}
	return rows
}

func (t *Trainer) read() ([]byte, error) {
	if t.reader == nil {
		return nil, errors.New("Trainer reader is not bound.")
	}
	data, err := t.reader(t.startAddr, t.length)
	if err != nil {
		return nil, err
	}
	if len(data) < t.length {
		return nil, errors.New("Trainer read returned too few bytes.")
	}
	return append([]byte(nil), data[:t.length]...), nil
}

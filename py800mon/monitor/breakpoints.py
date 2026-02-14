import curses

from ..actions import Actions
from ..app import VisualRpcComponent
from ..breakpoints import format_bp_condition, parse_bp_clauses
from ..datastructures import BreakpointClauseEntry
from ..rpc import RpcException
from ..ui import Color, DialogInput, DialogWidget, GridWidget
from ..ui import InputWidget
from .appstate import state


class BreakpointsViewer(VisualRpcComponent):
    def __init__(self, rpc, window):
        super().__init__(rpc, window)
        self.grid = GridWidget(window, col_gap=0)
        self.grid.add_column("index", width=0, attr=Color.ADDRESS.attr())
        self.grid.add_column("expr", width=0, attr=Color.TEXT.attr())
        self._last_snapshot = None
        self._last_state_seq = None
        self._enabled = False
        self._rows = []
        self._input_active = False
        self._pending_add_clauses = None
        self._pending_delete = None
        self._pending_clear = False
        self._pending_enabled = None
        self._refresh_requested = False
        self._clear_dialog = DialogWidget(self.window)
        self._input_widget = InputWidget(
            self.window,
            max_length=None,
            on_change=self._on_input_change,
        )

    async def update(self):
        if not state.breakpoints_supported:
            return False
        changed = await self._apply_pending_ops()
        cur_seq = state.state_seq
        if (
            not self._refresh_requested
            and self._last_state_seq == cur_seq
            and self._last_snapshot
        ):
            return changed
        self._last_state_seq = cur_seq
        try:
            bp = await self.rpc.breakpoint_list()
        except RpcException:
            return changed
        self._refresh_requested = False
        snapshot = bp
        if snapshot == self._last_snapshot:
            return changed
        self._last_snapshot = snapshot
        self._enabled = bp.enabled
        self._rows = list(bp.clauses)
        return True

    def render(self, force_redraw=False):
        ih = self.window._ih
        if ih <= 0:
            return
        overlay_rows = 1 if (self._input_active or self._clear_dialog.active) else 0
        self.window.set_tag_active("bp_enabled", self._enabled)
        self.grid.set_viewport(y=overlay_rows, height=max(0, ih - overlay_rows))

        rows = []
        if not self._rows:
            rows.append(("", "No breakpoint clauses."))
            self.grid.set_selected_row(None)
        else:
            for idx, clause in enumerate(self._rows, start=1):
                rows.append((f"#{idx:02d} ", self._format_clause_text(clause)))
            selected = self.grid.selected_row
            if selected is None:
                self.grid.set_selected_row(None)
            else:
                self.grid.set_selected_row(selected)
        self.grid.set_data(rows)
        self.grid.render()

        if self._clear_dialog.active:
            self._clear_dialog.render()
        elif self._input_active:
            self.window.cursor = (0, 0)
            color = Color.INPUT_INVALID if self._input_widget.invalid else Color.TEXT
            attr = color.attr() | curses.A_REVERSE
            self.window.print(self._input_widget.buffer, attr=attr)
            self.window.fill_to_eol(attr=attr)

    def _format_clause_text(self, clause):
        if not isinstance(clause, BreakpointClauseEntry):
            return str(clause)
        parts = []
        for cond in clause.conditions:
            parts.append(format_bp_condition(cond))
        return " AND ".join(parts)

    def handle_input(self, ch):
        if self._clear_dialog.active:
            result = self._clear_dialog.handle_input(ch)
            if result == DialogInput.CONFIRM:
                self._pending_clear = True
            return not result == DialogInput.NONE
        if ch == ord("/"):
            self._open_input("")
            return True
        if self.grid.handle_input(ch):
            return True
        if ch in (curses.KEY_DC, 330):
            self._queue_delete_selected()
            return True
        if ch in (ord("c"), ord("C")):
            self._clear_dialog.activate("Clear all breakpoints?", "YES")
            return True
        if ch == ord(" ") or ch in (ord("e"), ord("E")):
            self._pending_enabled = not self._enabled
            return True
        return False

    def _queue_delete_selected(self):
        idx = self.grid.selected_row
        if idx is None:
            return
        self._pending_delete = idx
        if idx >= len(self._rows) - 1:
            if len(self._rows) <= 1:
                self.grid.set_selected_row(None)
            else:
                self.grid.set_selected_row(len(self._rows) - 2)

    def _close_input(self):
        self._input_active = False
        self._input_widget.set_invalid(False)
        self._input_widget.deactivate()
        self.app.dispatch_action(Actions.SET_INPUT_FOCUS, None)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _open_input(self, initial: str):
        self._input_active = True
        self._input_widget.activate(str(initial))
        self._input_widget.set_invalid(False)
        self.app.dispatch_action(Actions.SET_INPUT_FOCUS, self._handle_text_input)
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _on_input_change(self, query):
        text = str(query).strip()
        if not text:
            self._input_widget.set_invalid(False)
            return
        try:
            parse_bp_clauses(text)
            self._input_widget.set_invalid(False)
        except ValueError:
            self._input_widget.set_invalid(True)

    def _handle_text_input(self, ch):
        if ch == 27:
            self._close_input()
            return True
        if ch in (10, 13, curses.KEY_ENTER):
            if self._input_widget.invalid:
                return True
            text = self._input_widget.buffer.strip()
            if text:
                try:
                    self._pending_add_clauses = parse_bp_clauses(text)
                except ValueError:
                    self._input_widget.set_invalid(True)
                    return True
            self._close_input()
            return True
        if self._input_widget.handle_key(ch):
            return True
        return True

    async def _apply_pending_ops(self):
        changed = False
        if self._pending_clear:
            self._pending_clear = False
            try:
                await self.rpc.breakpoint_clear()
                self.grid.set_selected_row(None)
                self._refresh_requested = True
                changed = True
            except RpcException:
                pass
        if self._pending_delete is not None:
            idx = self._pending_delete
            self._pending_delete = None
            try:
                await self.rpc.breakpoint_delete_clause(idx)
                self._refresh_requested = True
                changed = True
            except RpcException:
                pass
        if self._pending_enabled is not None:
            enabled = self._pending_enabled
            self._pending_enabled = None
            try:
                await self.rpc.breakpoint_set_enabled(enabled)
                self._refresh_requested = True
                changed = True
            except RpcException:
                pass
        if self._pending_add_clauses is not None:
            clauses = list(self._pending_add_clauses)
            self._pending_add_clauses = None
            for clause in clauses:
                try:
                    await self.rpc.breakpoint_add_clause(list(clause))
                    self._refresh_requested = True
                    changed = True
                except RpcException:
                    break
        return changed

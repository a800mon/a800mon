import asyncio
import time

from ..actions import Actions
from ..app import EventType
from ..datastructures import CpuState
from ..atari.disasm import disasm_6502_one
from ..emulator import CAP_MONITOR_BREAKPOINTS
from ..rpc import RpcException
from .appstate import state


class StatusUpdater:
    def __init__(
        self,
        rpc,
        dispatcher,
        paused_interval=1.0,
        running_interval=0.05,
        error_interval=1.0,
    ):
        self._rpc = rpc
        self._dispatcher = dispatcher
        self._paused_interval = float(paused_interval)
        self._running_interval = float(running_interval)
        self._error_interval = float(error_interval)
        self._wake_event = asyncio.Event()
        self._caps_synced = False
        self._last_caps_attempt = 0.0

    def request_refresh(self):
        self._wake_event.set()

    async def run(self, event_queue):
        force_cpu_refresh = False
        while True:
            await self._poll_once(force_cpu_refresh)
            force_cpu_refresh = False
            await event_queue.put((EventType.STATUS, None))
            interval = (
                self._error_interval
                if state.last_rpc_error
                else self._paused_interval if state.paused else self._running_interval
            )
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=interval)
                self._wake_event.clear()
                force_cpu_refresh = True
            except asyncio.TimeoutError:
                pass

    async def _poll_once(self, force_cpu_refresh=False):
        had_error = state.last_rpc_error != ""
        try:
            status = await self._rpc.status()
        except RpcException:
            self._sync_rpc_error()
            return

        changed = (
            state.paused != status.paused
            or state.emu_ms != status.emu_ms
            or state.reset_ms != status.reset_ms
            or state.crashed != status.crashed
            or state.state_seq != status.state_seq
        )
        if changed:
            self._dispatcher.dispatch(Actions.SET_STATUS, status)
        if changed or force_cpu_refresh:
            await self._update_cpu()
        now = time.monotonic()
        need_caps = had_error or not self._caps_synced
        if need_caps and now - self._last_caps_attempt >= 1.0:
            self._last_caps_attempt = now
            await self._update_capabilities()
        self._sync_rpc_error()

    async def _update_cpu(self):
        try:
            data = await self._rpc.cpu_state()
        except RpcException:
            return

        ypos, xpos, pc, a, x, y, s, p = data
        cpu = CpuState(ypos=ypos, xpos=xpos, pc=pc, a=a, x=x, y=y, s=s, p=p)
        cpu_disasm = ""
        try:
            code = await self._rpc.read_memory(pc, 3)
            cpu_disasm = disasm_6502_one(pc, code)
        except (RpcException, RuntimeError):
            pass
        self._dispatcher.dispatch(Actions.SET_CPU, (cpu, cpu_disasm))

    def _sync_rpc_error(self):
        error = self._rpc.last_error
        text = str(error) if error else None
        if state.last_rpc_error != text:
            self._dispatcher.dispatch(Actions.SET_LAST_RPC_ERROR, text)

    async def _update_capabilities(self):
        try:
            caps = await self._rpc.config()
        except RpcException:
            return
        self._caps_synced = True
        supported = CAP_MONITOR_BREAKPOINTS in set(caps)
        if state.breakpoints_supported != supported:
            self._dispatcher.dispatch(
                Actions.SET_BREAKPOINTS_SUPPORTED,
                supported,
            )

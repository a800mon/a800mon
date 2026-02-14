import asyncio
import enum
import struct

from .datastructures import (
    AnticState,
    Breakpoint,
    BreakpointClauseEntry,
    BreakpointConditionEntry,
    CartSlotState,
    CartState,
    CpuHistoryEntry,
    GtiaState,
    JumpsState,
    PiaState,
    PokeyState,
    StackEntry,
    StackState,
)


class RpcException(Exception):
    pass


class ConnectionError(RpcException):
    pass


class TransportError(RpcException):
    pass


class InvalidTransportCommand(TransportError):
    pass


class CommandError(RpcException):
    def __init__(self, status: int, data: bytes = b""):
        self.status = status
        self.data = data or b""
        if self.data:
            text = self.data.decode("utf-8", errors="replace")
            super().__init__(f"Command failed (status={status}): {text}")
        else:
            super().__init__(f"Command failed (status={status})")


class Status:
    def __init__(
        self,
        paused: bool,
        emu_ms: int,
        reset_ms: int,
        crashed: bool,
        state_seq: int,
    ):
        self.paused = paused
        self.emu_ms = emu_ms
        self.reset_ms = reset_ms
        self.crashed = crashed
        self.state_seq = state_seq


class Command(enum.Enum):
    PING = "ping"
    DLIST_ADDR = "dlist_addr"
    DLIST_DUMP = "dlist_dump"
    MEM_READ = "mem_read"
    MEM_READV = "mem_readv"
    CPU_STATE = "cpu_state"
    PAUSE = "pause"
    CONTINUE = "continue"
    STEP = "step"
    STEP_VBLANK = "step_vblank"
    STATUS = "status"
    RUN = "run"
    COLDSTART = "coldstart"
    WARMSTART = "warmstart"
    REMOVECARTRIGE = "removecartrige"
    STOP_EMULATOR = "stop_emulator"
    RESTART_EMULATOR = "restart_emulator"
    REMOVE_TAPE = "remove_tape"
    REMOVE_DISKS = "remove_disks"
    HISTORY = "history"
    BUILTIN_MONITOR = "builtin_monitor"
    WRITE_MEMORY = "write_memory"
    BP_CLEAR = "bp_clear"
    BP_ADD_CLAUSE = "bp_add_clause"
    BP_DELETE_CLAUSE = "bp_delete_clause"
    BP_SET_ENABLED = "bp_set_enabled"
    BP_LIST = "bp_list"
    BUILD_FEATURES = "build_features"
    CONFIG = "config"
    GTIA_STATE = "gtia_state"
    ANTIC_STATE = "antic_state"
    CART_STATE = "cart_state"
    JUMPS = "jumps"
    PIA_STATE = "pia_state"
    POKEY_STATE = "pokey_state"
    STACK = "stack"
    STEP_OVER = "step_over"
    RUN_UNTIL_RETURN = "run_until_return"
    BBRK = "bbrk"
    BLINE = "bline"
    SEARCH = "search"
    SET_REG = "set_reg"


class RpcClient:
    def __init__(self, transport):
        self._transport = transport
        self.last_error = None
        self._max_read = 0x400
        self._call_lock = None

    def _lock(self):
        if not self._call_lock:
            self._call_lock = asyncio.Lock()
        return self._call_lock

    async def call(self, command: Command, payload=None):
        async with self._lock():
            try:
                internal_command = self._transport.translate_command(command)
            except KeyError:
                raise InvalidTransportCommand(
                    f"Command not supported in the transport: {command}"
                )

            try:
                status, data = await self._transport.send(
                    internal_command, payload=payload
                )
            except (ConnectionError, ConnectionResetError, OSError) as ex:
                self.last_error = ex
                raise ConnectionError(ex)
            else:
                self.last_error = None

            if status == 0:
                return data
            raise CommandError(status, data)

    async def read_vector(self, addr: int):
        ptr = await self.call(Command.MEM_READ, struct.pack("<HH", addr, 2))
        if len(ptr) < 2:
            raise RpcException("MEM_READ vector payload too short")
        return ptr[0] | (ptr[1] << 8)

    async def read_byte(self, addr: int) -> int:
        data = await self.call(Command.MEM_READ, struct.pack("<HH", addr, 1))
        if len(data) < 1:
            raise RpcException("MEM_READ byte payload too short")
        return data[0]

    async def read_memory(self, addr: int, length: int):
        if length <= 0:
            return b""
        max_chunk = self._max_read
        if max_chunk <= 0 or length <= max_chunk:
            return await self.call(Command.MEM_READ, struct.pack("<HH", addr, length))
        data = bytearray()
        remaining = length
        cur = addr
        while remaining:
            take = max_chunk if remaining > max_chunk else remaining
            data += await self.call(Command.MEM_READ, struct.pack("<HH", cur, take))
            cur = (cur + take) & 0xFFFF
            remaining -= take
        return bytes(data)

    async def read_memory_multiple(self, ranges):
        payload = struct.pack("<H", len(ranges)) + b"".join(
            struct.pack("<HH", addr, ln) for addr, ln in ranges
        )
        return await self.call(Command.MEM_READV, payload)

    async def write_memory(self, addr: int, data: bytes):
        payload = bytes(data)
        if len(payload) > 0xFFFF:
            raise RpcException(
                f"WRITE_MEMORY payload too long: {len(payload)} bytes (max 65535)"
            )
        frame = struct.pack("<HH", addr & 0xFFFF, len(payload)) + payload
        await self.call(Command.WRITE_MEMORY, frame)

    async def read_display_list(self, start_addr: int | None = None):
        payload = None
        if start_addr is not None:
            payload = struct.pack("<H", int(start_addr) & 0xFFFF)
        return await self.call(Command.DLIST_DUMP, payload)

    async def breakpoint_clear(self):
        await self.call(Command.BP_CLEAR)

    async def breakpoint_add_clause(self, conditions):
        conds = list(conditions)
        if not conds:
            raise RpcException("Breakpoint clause must have at least one condition.")
        if len(conds) > 20:
            raise RpcException("Breakpoint clause exceeds maximum of 20 conditions.")
        payload = struct.pack("<HBB", 0xFFFF, len(conds), 0)
        for cond in conds:
            payload += struct.pack(
                "<BBHH",
                int(cond.cond_type) & 0xFF,
                int(cond.op) & 0xFF,
                int(cond.addr) & 0xFFFF,
                int(cond.value) & 0xFFFF,
            )
        data = await self.call(Command.BP_ADD_CLAUSE, payload)
        if len(data) < 2:
            raise RpcException("BP_ADD_CLAUSE payload too short")
        return struct.unpack_from("<H", data, 0)[0]

    async def breakpoint_delete_clause(self, clause_index: int):
        await self.call(
            Command.BP_DELETE_CLAUSE, struct.pack("<H", int(clause_index) & 0xFFFF)
        )

    async def breakpoint_set_enabled(self, enabled: bool):
        data = await self.call(Command.BP_SET_ENABLED, struct.pack("<B", 1 if enabled else 0))
        if len(data) < 1:
            raise RpcException("BP_SET_ENABLED payload too short")
        return bool(data[0])

    async def breakpoint_list(self) -> Breakpoint:
        data = await self.call(Command.BP_LIST)
        if len(data) < 3:
            raise RpcException("BP_LIST payload too short")
        enabled = bool(data[0])
        clause_count = struct.unpack_from("<H", data, 1)[0]
        offset = 3
        clauses = []
        for _ in range(clause_count):
            if offset + 2 > len(data):
                raise RpcException("BP_LIST payload too short (clause header)")
            cond_count = data[offset]
            offset += 2  # cond_count + reserved
            clause = []
            for _ in range(cond_count):
                if offset + 6 > len(data):
                    raise RpcException("BP_LIST payload too short (condition)")
                cond_type, op, addr, value = struct.unpack_from("<BBHH", data, offset)
                clause.append(
                    BreakpointConditionEntry(
                        cond_type=cond_type & 0xFF,
                        op=op & 0xFF,
                        addr=addr & 0xFFFF,
                        value=value & 0xFFFF,
                    )
                )
                offset += 6
            clauses.append(BreakpointClauseEntry(conditions=tuple(clause)))
        return Breakpoint(enabled=enabled, clauses=tuple(clauses))

    async def build_features(self) -> list[int]:
        data = await self.call(Command.BUILD_FEATURES)
        if len(data) < 2:
            raise RpcException("BUILD_FEATURES payload too short")
        count = struct.unpack_from("<H", data, 0)[0]
        expected = 2 + count * 2
        if len(data) < expected:
            raise RpcException(
                f"BUILD_FEATURES payload too short: got={len(data)} expected={expected}"
            )
        return [cap for (cap,) in struct.iter_unpack("<H", data[2:expected])]

    async def config(self) -> list[int]:
        return await self.build_features()

    async def status(self):
        data = await self.call(Command.STATUS)
        if len(data) < 21:
            raise RpcException("STATUS payload too short")
        paused_byte, emu_ms, reset_ms, state_seq = struct.unpack("<BQQI", data[:21])
        paused = bool(paused_byte & 0x01)
        crashed = bool(paused_byte & 0x80)
        return Status(
            paused=paused,
            emu_ms=emu_ms,
            reset_ms=reset_ms,
            crashed=crashed,
            state_seq=state_seq,
        )

    async def cpu_state(self):
        data = await self.call(Command.CPU_STATE)
        if len(data) < 11:
            raise RpcException("CPU_STATE payload too short")
        return struct.unpack("<HHHBBBBB", data[:11])

    async def history(self):
        data = await self.call(Command.HISTORY)
        if len(data) < 1:
            raise RpcException("HISTORY payload too short")
        count = data[0]
        expected = 1 + count * 7
        if len(data) < expected:
            raise RpcException(
                f"HISTORY payload too short: got={len(data)} expected={expected}"
            )
        return [
            CpuHistoryEntry(y=y, x=x, pc=pc, op0=op0, op1=op1, op2=op2)
            for y, x, pc, op0, op1, op2 in struct.iter_unpack("<BBHBBB", data[1:expected])
        ]

    async def gtia_state(self) -> GtiaState:
        data = await self.call(Command.GTIA_STATE)
        if len(data) < 30:
            raise RpcException("GTIA_STATE payload too short")
        (
            hposp,
            hposm,
            sizep,
            sizem,
            grafp,
            grafm,
            colpm,
            colpf,
            colbk,
            prior,
            vdelay,
            gractl,
        ) = struct.unpack("<4s4s4sB4sB4s4sBBBB", data[:30])
        return GtiaState(
            hposp=tuple(hposp),
            hposm=tuple(hposm),
            sizep=tuple(sizep),
            sizem=sizem,
            grafp=tuple(grafp),
            grafm=grafm,
            colpm=tuple(colpm),
            colpf=tuple(colpf),
            colbk=colbk,
            prior=prior,
            vdelay=vdelay,
            gractl=gractl,
        )

    async def antic_state(self) -> AnticState:
        data = await self.call(Command.ANTIC_STATE)
        if len(data) < 12:
            raise RpcException("ANTIC_STATE payload too short")
        dmactl, chactl, dlist, hscrol, vscrol, pmbase, chbase, vcount, nmien, ypos = struct.unpack(
            "<BBHBBBBBBH", data[:12]
        )
        return AnticState(
            dmactl=dmactl,
            chactl=chactl,
            dlist=dlist,
            hscrol=hscrol,
            vscrol=vscrol,
            pmbase=pmbase,
            chbase=chbase,
            vcount=vcount,
            nmien=nmien,
            ypos=ypos,
        )

    async def cartrige_state(self) -> CartState:
        data = await self.call(Command.CART_STATE)
        if len(data) < 25:
            raise RpcException("CART_STATE payload too short")
        fields = struct.unpack("<BBhIIBBhIIB", data[:25])
        (
            autoreboot,
            main_present,
            main_type,
            main_state,
            main_size_kb,
            main_raw,
            piggy_present,
            piggy_type,
            piggy_state,
            piggy_size_kb,
            piggy_raw,
        ) = fields
        return CartState(
            autoreboot=autoreboot,
            main=CartSlotState(
                present=main_present,
                cart_type=main_type,
                state=main_state,
                size_kb=main_size_kb,
                raw=main_raw,
            ),
            piggy=CartSlotState(
                present=piggy_present,
                cart_type=piggy_type,
                state=piggy_state,
                size_kb=piggy_size_kb,
                raw=piggy_raw,
            ),
        )

    async def jumps(self) -> JumpsState:
        data = await self.call(Command.JUMPS)
        if len(data) < 1:
            raise RpcException("JUMPS payload too short")
        count = data[0]
        expected = 1 + count * 2
        if len(data) < expected:
            raise RpcException(
                f"JUMPS payload too short: got={len(data)} expected={expected}"
            )
        pcs = tuple(pc for (pc,) in struct.iter_unpack("<H", data[1:expected]))
        return JumpsState(pcs=pcs)

    async def pia_state(self) -> PiaState:
        data = await self.call(Command.PIA_STATE)
        if len(data) < 4:
            raise RpcException("PIA_STATE payload too short")
        pactl, pbctl, porta, portb = struct.unpack("<BBBB", data[:4])
        return PiaState(pactl=pactl, pbctl=pbctl, porta=porta, portb=portb)

    async def pokey_state(self) -> PokeyState:
        data = await self.call(Command.POKEY_STATE)
        if len(data) < 15:
            raise RpcException("POKEY_STATE payload too short")
        (
            stereo_enabled,
            audf1,
            audc1,
            audctl1,
            kbcode,
            irqen,
            irqst,
            skstat,
            skctl,
        ) = struct.unpack("<B4s4sBBBBBB", data[:15])
        audf2 = None
        audc2 = None
        audctl2 = None
        if stereo_enabled:
            if len(data) < 24:
                raise RpcException("POKEY_STATE payload too short (chip2_data)")
            audf2, audc2, audctl2 = struct.unpack("<4s4sB", data[15:24])
        return PokeyState(
            stereo_enabled=stereo_enabled,
            audf1=tuple(audf1),
            audc1=tuple(audc1),
            audctl1=audctl1,
            kbcode=kbcode,
            irqen=irqen,
            irqst=irqst,
            skstat=skstat,
            skctl=skctl,
            audf2=tuple(audf2) if audf2 is not None else None,
            audc2=tuple(audc2) if audc2 is not None else None,
            audctl2=audctl2,
        )

    async def stack(self) -> StackState:
        data = await self.call(Command.STACK)
        if len(data) < 2:
            raise RpcException("STACK payload too short")
        s = data[0]
        count = data[1]
        expected = 2 + count * 2
        if len(data) < expected:
            raise RpcException(
                f"STACK payload too short: got={len(data)} expected={expected}"
            )
        entries = tuple(
            StackEntry(stack_off=stack_off, value=value)
            for stack_off, value in struct.iter_unpack("<BB", data[2:expected])
        )
        return StackState(s=s, entries=entries)

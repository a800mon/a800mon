import asyncio
import enum
import struct

from .rpc import Command, ConnectionError


class SocketCommand(enum.IntEnum):
    PING = 1
    DLIST_ADDR = 2
    DLIST_DUMP = 4
    MEM_READ = 3
    CPU_STATE = 5
    PAUSE = 6
    CONTINUE = 7
    STEP = 8
    STEP_VBLANK = 9
    STATUS = 10
    RUN = 12
    COLDSTART = 13
    WARMSTART = 14
    REMOVECARTRIGE = 15
    STOP_EMULATOR = 16
    RESTART_EMULATOR = 28
    REMOVE_TAPE = 17
    REMOVE_DISKS = 18
    HISTORY = 19
    BUILTIN_MONITOR = 20
    WRITE_MEMORY = 21
    BP_CLEAR = 22
    BP_ADD_CLAUSE = 23
    BP_DELETE_CLAUSE = 24
    BP_SET_ENABLED = 25
    BP_LIST = 26
    BUILD_FEATURES = 27
    CONFIG = 27
    GTIA_STATE = 29
    ANTIC_STATE = 30
    CART_STATE = 31
    JUMPS = 32
    PIA_STATE = 33
    POKEY_STATE = 34
    STACK = 35
    STEP_OVER = 36
    RUN_UNTIL_RETURN = 37
    BBRK = 38
    BLINE = 39
    SEARCH = 41
    SET_REG = 42


SUPPORTED_COMMANDS = {
    Command.PING: 1,
    Command.DLIST_ADDR: 2,
    Command.DLIST_DUMP: 4,
    Command.MEM_READ: 3,
    Command.MEM_READV: 11,
    Command.CPU_STATE: 5,
    Command.PAUSE: 6,
    Command.CONTINUE: 7,
    Command.STEP: 8,
    Command.STEP_VBLANK: 9,
    Command.STATUS: 10,
    Command.RUN: 12,
    Command.COLDSTART: 13,
    Command.WARMSTART: 14,
    Command.REMOVECARTRIGE: 15,
    Command.STOP_EMULATOR: 16,
    Command.RESTART_EMULATOR: 28,
    Command.REMOVE_TAPE: 17,
    Command.REMOVE_DISKS: 18,
    Command.HISTORY: 19,
    Command.BUILTIN_MONITOR: 20,
    Command.WRITE_MEMORY: 21,
    Command.BP_CLEAR: 22,
    Command.BP_ADD_CLAUSE: 23,
    Command.BP_DELETE_CLAUSE: 24,
    Command.BP_SET_ENABLED: 25,
    Command.BP_LIST: 26,
    Command.BUILD_FEATURES: 27,
    Command.CONFIG: 27,
    Command.GTIA_STATE: 29,
    Command.ANTIC_STATE: 30,
    Command.CART_STATE: 31,
    Command.JUMPS: 32,
    Command.PIA_STATE: 33,
    Command.POKEY_STATE: 34,
    Command.STACK: 35,
    Command.STEP_OVER: 36,
    Command.RUN_UNTIL_RETURN: 37,
    Command.BBRK: 38,
    Command.BLINE: 39,
    Command.SEARCH: 41,
    Command.SET_REG: 42,
}


class SocketTransport:
    def __init__(self, path):
        self.path = path
        self._reader = None
        self._writer = None
        self._connected = False
        self._timeout = 0.5
        self._config_caps = ()

    def translate_command(self, command: Command):
        return SUPPORTED_COMMANDS[command]

    async def connect(self):
        await self._disconnect()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.path), timeout=self._timeout
            )
        except (OSError, asyncio.TimeoutError) as ex:
            raise ConnectionError(f"Cannot connect to socket {self.path}: {ex}")
        self._reader = reader
        self._writer = writer
        self._connected = True
        await self._read_config_on_connect()

    async def _disconnect(self):
        writer = self._writer
        self._connected = False
        self._reader = None
        self._writer = None
        self._config_caps = ()
        if not writer:
            return
        writer.close()
        try:
            await writer.wait_closed()
        except (asyncio.TimeoutError, ConnectionError, OSError, IOError):
            pass

    async def _ensure_connected(self):
        if self._connected and self._reader and self._writer:
            return
        await self.connect()

    async def _read_config_on_connect(self):
        if not self._writer:
            return
        packet = bytes([SocketCommand.BUILD_FEATURES]) + struct.pack("<H", 0)
        try:
            self._writer.write(packet)
            await asyncio.wait_for(self._writer.drain(), timeout=self._timeout)
            hdr = await self._read_exact(3)
            status, ln = hdr[0], hdr[1] | (hdr[2] << 8)
            data = await self._read_exact(ln) if ln else b""
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError, RuntimeError):
            self._config_caps = ()
            return
        if status != 0 or len(data) < 2:
            self._config_caps = ()
            return
        count = data[0] | (data[1] << 8)
        max_items = (len(data) - 2) // 2
        if count > max_items:
            count = max_items
        offset = 2
        caps = []
        for _ in range(count):
            caps.append(data[offset] | (data[offset + 1] << 8))
            offset += 2
        self._config_caps = tuple(caps)

    async def _read_exact(self, ln: int):
        if not self._reader:
            raise ConnectionError("Socket not connected")
        try:
            return await asyncio.wait_for(
                self._reader.readexactly(ln), timeout=self._timeout
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            raise ConnectionError("Packet timeout")
        except asyncio.IncompleteReadError:
            await self._disconnect()
            raise ConnectionError("Incorrect data frame")
        except OSError as ex:
            await self._disconnect()
            raise ConnectionError(ex)

    async def send(self, command, payload=None):
        payload = payload or b""
        packet = bytes([command]) + struct.pack("<H", len(payload)) + payload

        await self._ensure_connected()
        try:
            if not self._writer:
                raise ConnectionError("Socket not connected")
            self._writer.write(packet)
            await asyncio.wait_for(self._writer.drain(), timeout=self._timeout)

            hdr = await self._read_exact(3)
            status, ln = hdr[0], hdr[1] | (hdr[2] << 8)
            if ln == 0:
                return status, b""
            data = await self._read_exact(ln)
            return status, data
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError, RuntimeError) as ex:
            await self._disconnect()
            if isinstance(ex, ConnectionError):
                raise
            raise ConnectionError(ex)

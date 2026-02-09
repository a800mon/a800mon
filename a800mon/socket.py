import enum
import socket
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
}


class SocketTransport:
    def __init__(self, path):
        self.path = path
        self._s = None
        self._connected = False

    def translate_command(self, command: Command):
        return SUPPORTED_COMMANDS[command]

    def connect(self):
        try:
            self._s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._s.connect(self.path)
            self._s.settimeout(0.5)
        except (IOError, FileNotFoundError) as ex:
            raise ConnectionError(f"Cannot connect to socket {self.path}: {ex}")

    def send(self, command, payload=None):
        payload = payload or b""

        if not self._connected:
            self.connect()

        retries = 3

        while retries:
            try:
                self._s.sendall(
                    bytes([command]) + struct.pack("<H", len(payload)) + payload
                )
            except TimeoutError:
                raise ConnectionError("Packet timeout")
            except socket.error:
                try:
                    self._s.close()
                except socket.error:
                    pass
                self._connected = False
                self.connect()
                retries -= 1
                continue
            else:
                break

        try:
            hdr = self._s.recv(3)
            status, ln = hdr[0], hdr[1] | (hdr[2] << 8)
        except TimeoutError:
            raise ConnectionError("Packet timeout")
        except IndexError:
            raise IOError("Incorrect data frame")
        data = b""
        if status == 0:
            while len(data) < ln:
                data += self._s.recv(ln - len(data))
        return status, data

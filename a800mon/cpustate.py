from .app import RpcComponent
from .appstate import state
from .datastructures import CpuState
from .rpc import Command, RpcException


class CpuStateViewer(RpcComponent):
    def update(self):
        try:
            data = self.rpc.cpu_state()
        except RpcException:
            pass
        else:
            ypos, xpos, pc, a, x, y, s, p = data
            state.cpu = CpuState(ypos=ypos, xpos=xpos, pc=pc, a=a, x=x, y=y, s=s, p=p)

    def render(self, force_redraw=False):
        self.window.print_line(repr(state.cpu))

    def handle_input(self, ch):
        if ch == ord("p"):
            self.rpc.call(Command.PAUSE)
        if ch == ord("s"):
            self.rpc.call(Command.STEP)
        if ch == ord("v"):
            self.rpc.call(Command.STEP_VBLANK)
        if ch == ord("c"):
            self.rpc.call(Command.CONTINUE)

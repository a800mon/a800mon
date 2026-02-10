from .app import VisualRpcComponent
from .appstate import state, store
from .datastructures import CpuState
from .rpc import RpcException


class CpuStateViewer(VisualRpcComponent):
    def update(self):
        try:
            data = self.rpc.cpu_state()
        except RpcException:
            pass
        else:
            ypos, xpos, pc, a, x, y, s, p = data
            cpu = CpuState(ypos=ypos, xpos=xpos, pc=pc, a=a, x=x, y=y, s=s, p=p)
            store.set_cpu(cpu)

    def render(self, force_redraw=False):
        self.window.print_line(repr(state.cpu))

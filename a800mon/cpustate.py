from .app import VisualRpcComponent
from .appstate import state, store
from .datastructures import CpuState
from .disasm import disasm_6502_one
from .rpc import RpcException


class CpuStateViewer(VisualRpcComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cpu_disasm = ""

    def update(self):
        try:
            data = self.rpc.cpu_state()
        except RpcException:
            pass
        else:
            ypos, xpos, pc, a, x, y, s, p = data
            cpu = CpuState(ypos=ypos, xpos=xpos, pc=pc, a=a, x=x, y=y, s=s, p=p)
            store.set_cpu(cpu)
            try:
                code = self.rpc.read_memory(pc, 3)
                self._cpu_disasm = disasm_6502_one(pc, code)
            except (RpcException, RuntimeError):
                self._cpu_disasm = ""

    def render(self, force_redraw=False):
        line = repr(state.cpu)
        if self._cpu_disasm:
            line += f"  {self._cpu_disasm}"
        self.window.print(line)
        self.window.clear_to_eol()

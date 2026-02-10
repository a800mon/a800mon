import curses
import time


class StopLoop(Exception):
    pass


class Component:
    def update(self):
        pass

    def post_render(self):
        pass


class InputComponent(Component):
    def handle_input(self, ch):
        return False


class RpcComponent(Component):
    def __init__(self, rpc, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rpc = rpc


class VisualComponent(Component):
    def __init__(self, window):
        self.window = window

    def render(self, force_redraw=False):
        raise NotImplementedError(self)


class VisualRpcComponent(VisualComponent):
    def __init__(self, rpc, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rpc = rpc


class App:
    def __init__(self, screen):
        self._screen = screen
        self._components = []
        self._visual_components = []
        self._input_components = []

    def add_component(self, component: Component):
        self._components.append(component)
        if isinstance(component, VisualComponent):
            self._screen.add(component.window)
            self._visual_components.append(component)
        if isinstance(component, InputComponent):
            self._input_components.append(component)

    def rebuild_screen(self):
        self._screen.rebuild()
        for component in self._visual_components:
            component.render(force_redraw=True)
        self._screen.update()

    def loop(self, iter_time=0.025):
        self._screen.initialize()
        self.rebuild_screen()

        try:
            while True:
                start_time = time.time()
                self.handle_input()
                self.update_state()
                self.render_components()

                time_diff = time.time() - start_time
                try:
                    from .appstate import store
                    store.set_frame_time_ms(int(time_diff * 1000.0))
                except Exception:
                    pass
                sleep_time = iter_time - time_diff
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except StopLoop:
            pass

    def handle_input(self):
        ch = self._screen.get_input_char()
        if ch == curses.KEY_RESIZE:
            self.rebuild_screen()
        if ch == -1:
            return
        for component in self._input_components:
            if component.handle_input(ch):
                return

    def update_state(self):
        for component in self._components:
            component.update()

    def render_components(self):
        for component in self._visual_components:
            component.render()
        self._screen.update()
        for component in self._components:
            component.post_render()

import curses
import time


class StopLoop(Exception):
    pass


class Component:
    def __init__(self, window):
        self.window = window

    def update(self):
        pass

    def handle_input(self, ch):
        pass

    def render(self, force_redraw=False):
        raise NotImplementedError(self)


class RpcComponent(Component):
    def __init__(self, rpc, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rpc = rpc


class App:
    def __init__(self, screen):
        self._screen = screen
        self._components = []

    def add_component(self, component: Component):
        self._components.append(component)
        self._screen.add(component.window)

    def rebuild_screen(self):
        self._screen.rebuild()
        for component in self._components:
            component.render(force_redraw=True)
        self._screen.update()

    def loop(self, iter_time=0.1):
        self._screen.initialize()
        self.rebuild_screen()

        try:
            while True:
                start_time = time.time()
                self.handle_input()
                self.update_state()
                self.render_components()

                time_diff = time.time() - start_time
                sleep_time = iter_time - time_diff
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except StopLoop:
            pass

    def handle_input(self):
        ch = self._screen.get_input_char()
        if ch == curses.KEY_RESIZE:
            self.rebuild_screen()
        if ch in (ord("q"), 27):
            raise StopLoop
        if not ch == -1:
            for component in self._components:
                component.handle_input(ch)

    def update_state(self):
        for component in self._components:
            component.update()

    def render_components(self):
        for component in self._components:
            component.render()
        self._screen.update()

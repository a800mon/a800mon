import asyncio
import curses
import enum
import time

from . import debug
from .monitor.appstate import state


class StopLoop(Exception):
    pass


class EventType(enum.Enum):
    INPUT = enum.auto()
    STATUS = enum.auto()


class Component:
    def __init__(self):
        self.app = None

    async def update(self):
        return False

    def handle_input(self, ch):
        return False


class RpcComponent(Component):
    def __init__(self, rpc, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rpc = rpc


class VisualComponent(Component):
    def __init__(self, window):
        super().__init__()
        self.window = window

    def render(self, force_redraw=False):
        raise NotImplementedError(self)


class VisualRpcComponent(VisualComponent):
    def __init__(self, rpc, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rpc = rpc


class App:
    def __init__(
        self,
        screen,
        dispatcher,
        status_updater=None,
        input_timeout_ms=200,
    ):
        self._screen = screen
        self.screen = screen
        self.dispatcher = dispatcher
        self._components = []
        self._input_components = []
        self._visual_components = []
        self._event_queue = asyncio.Queue()
        self._status_updater = status_updater
        self._input_timeout_ms = int(input_timeout_ms)

    def add_component(self, component: Component):
        component.app = self
        self._components.append(component)
        if isinstance(component, VisualComponent):
            self._screen.add(component.window)
            self._screen.set_window_input_handler(
                component.window,
                component.handle_input,
            )
            self._visual_components.append(component)
            return
        self._input_components.append(component)

    def dispatch_action(self, action, value=None):
        self.dispatcher.dispatch(action, value)

    def rebuild_screen(self):
        self._screen.rebuild()
        for component in self._visual_components:
            if not component.window.visible:
                continue
            component.render(force_redraw=True)
        self._screen.update()

    async def loop(self):
        from .actions import Actions

        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(self._handle_async_exception)
        self._screen.initialize()
        self._screen.set_input_timeout_ms(self._input_timeout_ms)
        self.rebuild_screen()
        input_pump = asyncio.create_task(self._input_event_pump())
        status_pump = None
        if self._status_updater:
            status_pump = asyncio.create_task(
                self._status_updater.run(self._event_queue)
            )

        try:
            while True:
                event_type, payload = await self._event_queue.get()
                start_time = time.time()
                was_frozen = state.ui_frozen
                had_input = False
                if event_type == EventType.INPUT:
                    had_input = self.handle_input(payload)
                if state.ui_frozen:
                    if event_type == EventType.INPUT and had_input and not was_frozen:
                        await self.render_components(force_redraw=True)
                    time_diff = time.time() - start_time
                    self.dispatch_action(
                        Actions.SET_FRAME_TIME_MS,
                        int(time_diff * 1000.0),
                    )
                    continue
                had_updates = await self.update_state()
                if self._status_updater and self.dispatcher.take_rpc_flushed():
                    self._status_updater.request_refresh()
                await self.render_components(
                    should_render=had_input or had_updates,
                    force_redraw=False,
                )
                time_diff = time.time() - start_time
                self.dispatch_action(
                    Actions.SET_FRAME_TIME_MS,
                    int(time_diff * 1000.0),
                )
        except StopLoop:
            pass
        finally:
            input_pump.cancel()
            tasks = [input_pump]
            if status_pump:
                status_pump.cancel()
                tasks.append(status_pump)
            await asyncio.gather(*tasks, return_exceptions=True)
            loop.set_exception_handler(previous_handler)

    def handle_input(self, ch):
        if ch == curses.KEY_RESIZE:
            self.rebuild_screen()
            return True
        if self._screen.has_input_focus():
            return self._screen.handle_input(ch)
        if self._screen.handle_input(ch):
            return True
        for component in self._input_components:
            if component.handle_input(ch):
                return True
        return False

    async def update_state(self):
        changed = False
        for component in self._components:
            changed = await component.update() or changed
        return changed

    async def render_components(self, should_render=False, force_redraw=False):
        if should_render or force_redraw:
            for component in self._visual_components:
                if not component.window.visible:
                    continue
                component.render(force_redraw=force_redraw)
        if force_redraw or any(
            component.window.visible and component.window._dirty
            for component in self._visual_components
        ):
            self._screen.update()

    async def _input_event_pump(self):
        while True:
            ch = await asyncio.to_thread(self._screen.get_input_char)
            if ch == -1:
                continue
            await self._event_queue.put((EventType.INPUT, ch))

    def _handle_async_exception(self, loop, context):
        exc = context.get("exception")
        if exc:
            debug.log(f"async loop exception: {exc!r}")

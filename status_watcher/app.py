from __future__ import annotations

import queue
import select
import sys
import termios
import threading
import time
import tty

from typing import Optional, Sequence

from rich.console import Console
from rich.live import Live

from status_watcher.config import REFRESH_SECONDS, resolve_source_specs
from status_watcher.history import HistoryStore
from status_watcher.monitor import load_all
from status_watcher.ui import build_layout


class KeyboardReader:
    def __init__(self) -> None:
        self.queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._enabled = sys.stdin.isatty()
        self._old_settings = None

    def start(self) -> None:
        if not self._enabled:
            return
        self._old_settings = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._enabled and self._old_settings is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_settings)

    def _run(self) -> None:
        while not self._stop.is_set():
            rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not rlist:
                continue

            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = ch
                rlist, _, _ = select.select([sys.stdin], [], [], 0.01)
                while rlist:
                    seq += sys.stdin.read(1)
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.01)
                self.queue.put(seq)
            else:
                self.queue.put(ch)

    def get_key(self) -> Optional[str]:
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None


def normalize_key(key: Optional[str]) -> Optional[str]:
    if key is None:
        return None

    keymap = {
        "\x1b[A": "up",
        "\x1bOA": "up",
        "\x1b[B": "down",
        "\x1bOB": "down",
        "k": "up",
        "K": "up",
        "j": "down",
        "J": "down",
        "r": "refresh",
        "R": "refresh",
        "q": "quit",
        "Q": "quit",
    }
    return keymap.get(key, key)


def refresh_statuses(source_specs, history_store: HistoryStore):
    return history_store.apply(load_all(source_specs))


def main(argv: Optional[Sequence[str]] = None) -> int:
    source_specs = resolve_source_specs(argv)
    console = Console()
    keyboard = KeyboardReader()
    history_store = HistoryStore()

    statuses = refresh_statuses(source_specs, history_store)
    selected = 0
    last_refresh = time.time()

    keyboard.start()
    try:
        with Live(
            build_layout(statuses, selected, last_refresh, REFRESH_SECONDS),
            console=console,
            refresh_per_second=8,
            screen=True,
        ) as live:
            while True:
                key = normalize_key(keyboard.get_key())
                needs_render = key is not None

                if key == "quit":
                    break
                elif key == "refresh":
                    statuses = refresh_statuses(source_specs, history_store)
                    if selected >= len(statuses):
                        selected = max(0, len(statuses) - 1)
                    last_refresh = time.time()
                elif key == "down" and statuses:
                    selected = min(len(statuses) - 1, selected + 1)
                elif key == "up" and statuses:
                    selected = max(0, selected - 1)

                if time.time() - last_refresh >= REFRESH_SECONDS:
                    statuses = refresh_statuses(source_specs, history_store)
                    if selected >= len(statuses):
                        selected = max(0, len(statuses) - 1)
                    last_refresh = time.time()
                    needs_render = True

                if needs_render:
                    live.update(build_layout(statuses, selected, last_refresh, REFRESH_SECONDS), refresh=True)

                time.sleep(0.05)
    finally:
        keyboard.stop()

    return 0

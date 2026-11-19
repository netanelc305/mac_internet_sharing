import os
import select
import sys
import termios
import tty
from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

KEYS_UP = ('\x1b[A', '\x1bOA', 'k')
KEYS_DOWN = ('\x1b[B', '\x1bOB', 'j')
KEYS_CONFIRM = ('\r', '\n')
KEYS_ABORT = ('\x1b', 'q', '\x04')
ESCAPE_SEQUENCE_TIMEOUT = 0.05
HINT = '↑/↓ move · space toggle · a all/none · enter confirm · q abort'


def read_key() -> str:
    """ Read a single key press from the terminal. """
    fd = sys.stdin.fileno()
    attributes = termios.tcgetattr(fd)
    try:
        # Unlike raw mode, Ctrl+C still raises KeyboardInterrupt
        tty.setcbreak(fd)
        key = os.read(fd, 1)
        if key == b'\x1b' and select.select([fd], [], [], ESCAPE_SEQUENCE_TIMEOUT)[0]:
            # Arrow keys are sent as an escape sequence
            key += os.read(fd, 2)
        return key.decode(errors='ignore')
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attributes)


def checkbox(console: Console, title: str, columns: list[str], rows: list[list[str]]) -> Optional[list[int]]:
    """
    Let the user choose any number of rows, all chosen by default.

    Return the chosen row indexes, or None if the user aborted or there is no terminal to ask on.
    """
    if not sys.stdin.isatty() or not console.is_terminal:
        return None

    chosen = [True] * len(rows)
    cursor = 0

    def render() -> Group:
        table = Table(title=title)
        for column in ['', *columns]:
            table.add_column(column)
        for index, row in enumerate(rows):
            table.add_row(Text('[x]' if chosen[index] else '[ ]'), *row, style='reverse' if index == cursor else None)
        return Group(table, Text(HINT, style='dim'))

    with Live(render(), console=console, auto_refresh=False) as live:
        while True:
            try:
                key = read_key()
            except KeyboardInterrupt:
                return None
            if key in KEYS_CONFIRM:
                return [index for index, is_chosen in enumerate(chosen) if is_chosen]
            if key in KEYS_ABORT:
                return None
            if key in KEYS_UP:
                cursor = (cursor - 1) % len(rows)
            elif key in KEYS_DOWN:
                cursor = (cursor + 1) % len(rows)
            elif key == ' ':
                chosen[cursor] = not chosen[cursor]
            elif key == 'a':
                chosen = [not all(chosen)] * len(rows)
            live.update(render(), refresh=True)

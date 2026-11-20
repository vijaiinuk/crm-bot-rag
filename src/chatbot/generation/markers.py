"""Strip citation markers like [2] or [1, 3] out of a token stream (S3.1.3b).

Text is passed through as it arrives, except what might still turn into a marker: an
unclosed "[" with digits after it, and trailing whitespace (dropped if a marker
follows). The first characters are also held until they can't be the NOT_FOUND
sentinel, so a "not found" reply never leaks a single token.
"""

import re

from chatbot.generation.prompt import NOT_FOUND

_MARKER = re.compile(r"[ \t]?\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
_OPEN = re.compile(r"\[[\d,\s]{0,12}$")  # could still become a marker


class MarkerStream:
    def __init__(self) -> None:
        self._buf = ""
        self._decided = False
        self.not_found = False
        self.cited: list[int] = []  # marker numbers in order of first appearance

    def feed(self, delta: str) -> str:
        self._buf += delta
        return self._drain(final=False)

    def finish(self) -> str:
        return self._drain(final=True)

    def _drain(self, *, final: bool) -> str:
        if not self._decided:
            head = self._buf.lstrip()
            if not final and len(head) < len(NOT_FOUND) and NOT_FOUND.startswith(head):
                return ""  # could still be the sentinel
            self._decided = True
            self.not_found = head.startswith(NOT_FOUND)
        if self.not_found:
            self._buf = ""
            return ""
        cut = len(self._buf)
        if not final:
            if m := _OPEN.search(self._buf):
                cut = m.start()
            while cut > 0 and self._buf[cut - 1] in " \t":
                cut -= 1
        out, self._buf = self._buf[:cut], self._buf[cut:]
        return _MARKER.sub(self._record, out)

    def _record(self, m: re.Match[str]) -> str:
        for n in (int(x) for x in m.group(1).split(",")):
            if n not in self.cited:
                self.cited.append(n)
        return ""

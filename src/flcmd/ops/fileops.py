"""File operation engine: VFS-based copy/move/delete with progress,
conflict and error prompts. Toolkit-free: runs in a worker thread and
talks to the UI only through OpControl (shared state + ask/answer queues)."""

import queue
import threading

from .. import paths

CHUNK = 1 << 20

CONFLICT_BTNS = ["Overwrite", "Overwrite All", "Skip", "Skip All", "Cancel"]
ERROR_BTNS = ["Retry", "Skip", "Skip All", "Cancel"]


class Cancelled(Exception):
    pass


class OpControl:
    """Shared state between a worker thread and the UI pump."""

    def __init__(self):
        self.cancel_evt = threading.Event()
        self._lock = threading.Lock()
        self.done_bytes = self.total_bytes = 0
        self.done_items = self.total_items = 0
        self.current = ""
        self.error: str | None = None  # "cancelled" or failure text
        self._ask_q: queue.Queue = queue.Queue(1)
        self._ans_q: queue.Queue = queue.Queue(1)

    # -- worker side --------------------------------------------------------
    def check_cancel(self):
        if self.cancel_evt.is_set():
            raise Cancelled()

    def ask(self, text: str, buttons: list[str]) -> str:
        """Block until the UI answers (or cancels)."""
        self.check_cancel()
        self._ask_q.put((text, buttons))
        ans = self._ans_q.get()
        if ans == "Cancel":
            raise Cancelled()
        return ans

    def add_bytes(self, n: int):
        with self._lock:
            self.done_bytes += n

    def item_done(self, path: str):
        with self._lock:
            self.done_items += 1
            self.current = path

    def set_current(self, path: str):
        with self._lock:
            self.current = path

    # -- UI side -------------------------------------------------------------
    def pending_ask(self):
        try:
            return self._ask_q.get_nowait()
        except queue.Empty:
            return None

    def answer(self, ans: str):
        self._ans_q.put(ans)

    def snapshot(self):
        with self._lock:
            return (self.done_bytes, self.total_bytes,
                    self.done_items, self.total_items, self.current)


def run_in_thread(fn, ctl: OpControl) -> threading.Thread:
    def wrap():
        try:
            fn()
        except Cancelled:
            ctl.error = "cancelled"
        except Exception as e:  # surface anything unexpected in the UI
            ctl.error = f"{type(e).__name__}: {e}"
    t = threading.Thread(target=wrap, daemon=True)
    t.start()
    return t


def scan(vfs, items: list[str]) -> tuple[int, int]:
    """(total_bytes, total_items) under the given paths; dirs count as items."""
    bytes_ = items_ = 0
    stack = list(items)
    while stack:
        p = stack.pop()
        st = vfs.stat(p)
        items_ += 1
        if st.is_dir and not st.is_link:
            for e in vfs.listdir(p):
                stack.append(paths.join(p, e.name))
        else:
            bytes_ += st.size
    return bytes_, items_


def _guard(ctl: OpControl, policy: dict, path: str, fn) -> bool:
    """Run fn with retry/skip/cancel error handling. True if it ran."""
    while True:
        try:
            fn()
            return True
        except Cancelled:
            raise
        except OSError as e:
            if policy.get("skip_errors"):
                return False
            ans = ctl.ask(f"Error:\n{path}\n{e}", ERROR_BTNS)
            if ans == "Retry":
                continue
            if ans == "Skip All":
                policy["skip_errors"] = True
            return False


def _resolve_conflict(ctl: OpControl, policy: dict, dst: str) -> bool:
    """True = overwrite, False = skip this one."""
    ow = policy.get("overwrite")
    if ow is None:
        ans = ctl.ask(f"Target exists:\n{dst}", CONFLICT_BTNS)
        if ans == "Overwrite All":
            policy["overwrite"] = ow = True
        elif ans == "Skip All":
            policy["overwrite"] = ow = False
        else:
            return ans == "Overwrite"
    return ow


def _copy_file(sv, sp, dv, dp, ctl: OpControl):
    ctl.set_current(sp)
    try:
        with sv.open(sp, "rb") as fi, dv.open(dp, "wb") as fo:
            while chunk := fi.read(CHUNK):
                ctl.check_cancel()
                fo.write(chunk)
                ctl.add_bytes(len(chunk))
    except (Cancelled, OSError):
        try:  # no partial targets
            dv.remove(dp)
        except OSError:
            pass
        raise
    cs = getattr(dv, "copystat", None)
    if cs and sv is dv:
        cs(sp, dp)


def _copy_tree(sv, sp, dv, dp, ctl, policy, move: bool):
    st = sv.stat(sp)
    if st.is_dir and not st.is_link:
        if not dv.exists(dp):
            if not _guard(ctl, policy, dp, lambda: dv.mkdir(dp)):
                return
        for e in sv.listdir(sp):
            ctl.check_cancel()
            _copy_tree(sv, paths.join(sp, e.name), dv, paths.join(dp, e.name),
                       ctl, policy, move)
        if move:
            _guard(ctl, policy, sp, lambda: sv.rmdir(sp))
        ctl.item_done(sp)
        return
    if dv.exists(dp) and not _resolve_conflict(ctl, policy, dp):
        ctl.add_bytes(st.size)
        ctl.item_done(sp)
        return
    if _guard(ctl, policy, sp, lambda: _copy_file(sv, sp, dv, dp, ctl)) and move:
        _guard(ctl, policy, sp, lambda: sv.remove(sp))
    ctl.item_done(sp)


def copy_op(sv, items: list[str], dv, dst_dir: str, ctl: OpControl,
            move: bool = False):
    """Copy/move items (full paths) into dst_dir. Call from a worker thread."""
    if move and sv is dv:  # fast path: plain renames where possible
        rest = []
        for p in items:
            dst = paths.join(dst_dir, paths.basename(p))
            if p == dst:
                continue
            if dv.exists(dst):
                rest.append(p)
                continue
            try:
                sv.rename(p, dst)
            except OSError:  # cross-device etc: fall back to copy+delete
                rest.append(p)
        items = rest
        if not items:
            return
    ctl.total_bytes, ctl.total_items = scan(sv, items)
    policy: dict = {}
    for p in items:
        ctl.check_cancel()
        _copy_tree(sv, p, dv, paths.join(dst_dir, paths.basename(p)),
                   ctl, policy, move)


def delete_op(vfs, items: list[str], ctl: OpControl):
    _, ctl.total_items = scan(vfs, items)
    policy: dict = {}

    def rm(p):
        st = vfs.stat(p)
        if st.is_dir and not st.is_link:
            for e in vfs.listdir(p):
                ctl.check_cancel()
                rm(paths.join(p, e.name))
            _guard(ctl, policy, p, lambda: vfs.rmdir(p))
        else:
            _guard(ctl, policy, p, lambda: vfs.remove(p))
        ctl.item_done(p)

    for p in items:
        ctl.check_cancel()
        rm(p)

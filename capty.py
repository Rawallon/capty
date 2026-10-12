#!/usr/bin/env python3
"""Capty: area screen recorder (Linux: x11grab + slop, Windows: gdigrab). tkinter UI."""
import json
import os
import wave
import sys
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, simpledialog

WIN = sys.platform == "win32"
if WIN:
    import ctypes
    import ctypes.wintypes
    try:
        import pyaudiowpatch as pyaudio  # WASAPI incl. loopback (system audio); optional
    except ImportError:
        pyaudio = None
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor: tk + gdigrab use physical pixels
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Videos")
CONFIG_DIR = os.path.join(
    os.environ.get("APPDATA") if WIN else os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "capty")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
START_MENU_LINK = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Capty.lnk")


DEFAULT_HOTKEYS = {"record": "ctrl+alt+r", "stop": "ctrl+alt+s"}
WM_HOTKEY, WM_APP, MOD_NOREPEAT = 0x0312, 0x8000, 0x4000
MODIFIER_KEYSYMS = {"Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R", "Super_L", "Super_R",
                    "Meta_L", "Meta_R", "Caps_Lock", "Num_Lock", "ISO_Level3_Shift"}


def parse_hotkey(combo):
    """'ctrl+alt+s' -> (RegisterHotKey modifier mask, virtual-key code), or None if invalid."""
    parts = combo.lower().split("+")
    mods = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4}
    mask = 0
    for m in parts[:-1]:
        if m not in mods:
            return None
        mask |= mods[m]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        return mask, ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return mask, 0x70 + int(key[1:]) - 1
    return None


def tk_sequence(combo):
    """'ctrl+alt+s' -> '<Control-Alt-Key-s>' for window-local binding."""
    if not parse_hotkey(combo):
        return None
    names = {"ctrl": "Control", "alt": "Alt", "shift": "Shift"}
    parts = combo.lower().split("+")
    key = parts[-1]
    if (key.startswith("f") and len(key) > 1) or "shift" in parts:
        key = key.upper()
    return "<" + "-".join([names[m] for m in parts[:-1]] + ["Key", key]) + ">"


def list_audio_devices():
    """Selectable audio sources: [{key, label, kind: 'mic'|'sys', ...backend data}]."""
    devs = []
    if WIN:
        if not pyaudio:
            return devs
        p = pyaudio.PyAudio()
        try:
            api = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if d["hostApi"] != api["index"] or d["maxInputChannels"] < 1:
                    continue
                loop = bool(d.get("isLoopbackDevice"))
                name = d["name"].replace(" [Loopback]", "")
                kind = "sys" if loop else "mic"
                devs.append(dict(key=f"{kind}:{name}", kind=kind,
                                 label=("System audio: " if loop else "Mic: ") + name,
                                 index=i, rate=int(d["defaultSampleRate"]), channels=d["maxInputChannels"]))
        except Exception as e:
            print("Audio enumeration error:", e)
        finally:
            p.terminate()
    elif shutil.which("pactl"):
        try:
            out = subprocess.run(["pactl", "list", "sources"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True).stdout
        except OSError:
            return devs
        for block in out.split("Source #")[1:]:
            fields = {}
            for line in block.splitlines():
                k, _, v = line.strip().partition(": ")
                fields.setdefault(k, v)
            name = fields.get("Name")
            if not name:
                continue
            kind = "sys" if name.endswith(".monitor") else "mic"
            desc = fields.get("Description", name)
            devs.append(dict(key=f"{kind}:{name}", kind=kind, name=name,
                             label=("System audio: " if kind == "sys" else "Mic: ") + desc.replace("Monitor of ", "")))
    return sorted(devs, key=lambda d: d["kind"] != "sys")


class WinAudioRecorder:
    """Records each source to its own WAV (silence-padded so it stays on the video timeline).

    Sources can be switched on/off at any time: a disabled source's stream is closed (so a mic is really
    released) and the gap is filled with silence when it is enabled again.
    """

    def __init__(self, devices, base):
        self.devices = {d["key"]: d for d in devices}
        self.base = base
        self.srcs = {}  # key -> {wf, st, path, stream}
        self.lock = threading.Lock()
        self.p = None
        self.t0 = None

    def start(self, keys):
        self.p = pyaudio.PyAudio()
        self.t0 = time.time()
        self.apply(keys)

    def apply(self, keys):
        """Open streams for `keys`, close the rest. No-op until start() was called."""
        with self.lock:
            if self.p is None:
                return
            for key, dev in self.devices.items():
                src = self.srcs.get(key)
                if key in keys:
                    if not src or not src["stream"]:
                        self._open(key, dev, src)
                elif src and src["stream"]:
                    self._close_stream(src)

    def _open(self, key, dev, src):
        try:
            if not src:
                path = f"{self.base}_audio{len(self.srcs)}.wav"
                wf = wave.open(path, "wb")
                wf.setnchannels(dev["channels"])
                wf.setsampwidth(2)
                wf.setframerate(dev["rate"])
                src = {"wf": wf, "path": path, "stream": None,
                       "st": {"written": 0, "rate": dev["rate"], "ch": dev["channels"]}}
                self.srcs[key] = src
            src["stream"] = self.p.open(format=pyaudio.paInt16, channels=dev["channels"], rate=dev["rate"],
                                        input=True, input_device_index=dev["index"], frames_per_buffer=1024,
                                        stream_callback=self._callback(src))
        except Exception as e:
            print(f"Audio source {dev['label']} failed:", e)

    @staticmethod
    def _close_stream(src):
        try:
            src["stream"].stop_stream()
            src["stream"].close()
        finally:
            src["stream"] = None

    def _callback(self, src):
        wf, st = src["wf"], src["st"]

        def cb(data, frames, _ti, _status):
            # loopback delivers nothing while silent, and a re-enabled source has a gap: fill with silence
            gap = int((time.time() - self.t0) * st["rate"]) - st["written"] - frames
            if gap > st["rate"] // 5:
                wf.writeframes(bytes(gap * st["ch"] * 2))
                st["written"] += gap
            wf.writeframes(data)
            st["written"] += frames
            return None, pyaudio.paContinue
        return cb

    def stop(self):
        """Close everything; returns the WAV paths that were recorded."""
        with self.lock:
            if self.p is None:
                return []
            total = time.time() - self.t0
            paths = []
            for src in self.srcs.values():
                try:
                    if src["stream"]:
                        self._close_stream(src)
                    st = src["st"]
                    deficit = int(total * st["rate"]) - st["written"]
                    if deficit > 0:
                        src["wf"].writeframes(bytes(deficit * st["ch"] * 2))
                finally:
                    src["wf"].close()
                paths.append(src["path"])
            self.p.terminate()
            self.p = None
            return paths


def video_duration(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                             creationflags=NO_WINDOW).stdout
        return float(out.strip())
    except (OSError, ValueError):
        return 0.0


def mux_audio(video, wavs, audio_skip=0.0):
    """Replace `video` with a copy that has the WAVs mixed in as AAC (dropping the first `audio_skip` s)."""
    out = video + ".tmp.mp4"
    cmd = ["ffmpeg", "-y", "-i", video]
    for w in wavs:
        cmd += ["-ss", f"{audio_skip:.3f}", "-i", w]
    if len(wavs) == 1:
        amap = "1:a"
    else:
        ins = "".join(f"[{i + 1}:a]" for i in range(len(wavs)))
        cmd += ["-filter_complex", f"{ins}amix=inputs={len(wavs)}:duration=longest:normalize=0[a]"]
        amap = "[a]"
    cmd += ["-map", "0:v", "-map", amap, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-shortest", "-f", "mp4", out]
    subprocess.run(cmd, check=True, creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.replace(out, video)
    for w in wavs:
        os.remove(w)


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError as e:
        print("Could not save config:", e)


def install_start_menu():
    """Windows: add a Start Menu shortcut so Capty is searchable and launchable without a console."""
    here = os.path.dirname(os.path.abspath(__file__))
    ico = os.path.join(CONFIG_DIR, "capty.ico")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(os.path.join(here, "icon.png"), "rb") as fh:
        png = fh.read()
    w, h = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    with open(ico, "wb") as fh:  # ICO container with an embedded PNG
        fh.write(bytes([0, 0, 1, 0, 1, 0]) + bytes([w % 256, h % 256, 0, 0, 1, 0, 32, 0])
                 + len(png).to_bytes(4, "little") + (22).to_bytes(4, "little") + png)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{START_MENU_LINK}');"
          f"$s.TargetPath='{pyw}';$s.Arguments='\"{os.path.join(here, 'capty.py')}\"';"
          f"$s.WorkingDirectory='{here}';$s.IconLocation='{ico}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, creationflags=NO_WINDOW)
    print("Installed Start Menu shortcut:", START_MENU_LINK)

BORDER = 3
BORDER_COLOR = "#ff9900"


def virtual_screen():
    gm = ctypes.windll.user32.GetSystemMetrics
    return gm(76), gm(77), gm(78), gm(79)  # x, y, w, h across all monitors


def select_area_slop():
    """Linux: let slop draw the selection. Returns (x, y, w, h) or None."""
    try:
        res = subprocess.run(["slop", "-f", "%x %y %w %h"], check=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return tuple(map(int, res.stdout.split())) or None
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        print("slop error:", e)
        return None


def place(win, x, y, w, h):
    """Position a toplevel in physical pixels. On Windows, tk's geometry gets rescaled when the window
    lands on a monitor with different DPI scaling, so set the real window rect directly."""
    win.geometry(f"{w}x{h}{x:+d}{y:+d}")
    if WIN:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        # HWND_TOPMOST=-1, SWP_NOACTIVATE=0x10
        ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), x, y, w, h, 0x10)


def monitors():
    """Windows: [(x, y, w, h)] per monitor, in physical pixels."""
    rects = []
    proc_t = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_void_p)

    def cb(_m, _dc, r, _d):
        r = r.contents
        rects.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
    return rects or [virtual_screen()]


def select_area(root):
    """Windows: dim overlay on every monitor; drag to select. Returns (x, y, w, h) or None."""
    tops = []  # (toplevel, canvas, origin_x, origin_y)
    state = {"start": None, "result": None}

    def close(_e=None):
        root.unbind_all("<Escape>")
        for t, _c, _x, _y in tops:
            t.destroy()
        tops.clear()

    def redraw(cur):
        sx, sy = state["start"]
        for _t, c, ox, oy in tops:
            c.delete("sel")
            c.create_rectangle(sx - ox, sy - oy, cur[0] - ox, cur[1] - oy,
                               outline=BORDER_COLOR, width=2, fill="white", tags="sel")

    def press(e):
        state["start"] = (e.x_root, e.y_root)

    def drag(e):
        if state["start"]:
            redraw((e.x_root, e.y_root))

    def release(e):
        if state["start"]:
            sx, sy = state["start"]
            w, h = abs(e.x_root - sx), abs(e.y_root - sy)
            if w > 1 and h > 1:
                state["result"] = (min(sx, e.x_root), min(sy, e.y_root), w, h)
        close()

    # one window per monitor: a single window spanning monitors with different DPI scaling is unreliable
    for mx, my, mw, mh in monitors():
        t = tk.Toplevel(root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.attributes("-alpha", 0.3)
        t.configure(bg="black", cursor="crosshair")
        place(t, mx, my, mw, mh)
        c = tk.Canvas(t, bg="black", highlightthickness=0)
        c.pack(fill="both", expand=True)
        c.bind("<ButtonPress-1>", press)
        c.bind("<B1-Motion>", drag)
        c.bind("<ButtonRelease-1>", release)
        tops.append((t, c, mx, my))
    root.bind_all("<Escape>", close)
    tops[0][0].focus_force()
    while tops:  # wait until all overlays are closed
        root.update()
        time.sleep(0.01)
    return state["result"]


class Overlay:
    """Four thin topmost windows forming a ring just outside the selection."""

    def __init__(self, root):
        self.wins = []
        for _ in range(4):
            w = tk.Toplevel(root)
            w.overrideredirect(True)
            w.attributes("-topmost", True)
            w.configure(bg=BORDER_COLOR)
            w.withdraw()
            self.wins.append(w)

    def show(self, rect):
        x, y, w, h = rect
        t = BORDER
        geoms = [
            (w + 2 * t, t, x - t, y - t),
            (w + 2 * t, t, x - t, y + h),
            (t, h, x - t, y),
            (t, h, x + w, y),
        ]
        for win, (gw, gh, gx, gy) in zip(self.wins, geoms):
            win.deiconify()
            place(win, gx, gy, gw, gh)

    def hide(self):
        for w in self.wins:
            w.withdraw()


BG, BORDER_LINE, FG, MUTED = "#1e1e22", "#3a3a40", "#f2f2f7", "#9a9aa3"
HOVER, ACCENT, ACCENT_HOVER, ON, OFF = "#34343a", "#ff453a", "#ff6259", "#30a14e", BG
FONT = "Segoe UI" if WIN else "TkDefaultFont"
EMOJI = "Segoe UI Emoji" if WIN else "TkDefaultFont"
SYMBOL = "Segoe UI Symbol" if WIN else "TkDefaultFont"
KINDS = (("mic", "\U0001F3A4", "\U0001F3A4", "Microphones"), ("sys", "\U0001F50A", "\U0001F507", "System audio"))


class FlatButton(tk.Label):
    """Label-based flat button with hover state."""

    def __init__(self, parent, text, command, bg=BG, hover=HOVER, fg=FG, font=None, padx=10, pady=6, **kw):
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font or (FONT, 10), padx=padx, pady=pady,
                         cursor="hand2", **kw)
        self.command, self.base, self.hover, self.fg, self.enabled = command, bg, hover, fg, True
        self.bind("<Enter>", lambda e: self.enabled and super(FlatButton, self).config(bg=self.hover))
        self.bind("<Leave>", lambda e: super(FlatButton, self).config(bg=self.base))
        self.bind("<Button-1>", lambda e: self.enabled and self.command())

    def look(self, bg=None, hover=None, text=None, enabled=True):
        self.base = bg or self.base
        self.hover = hover or self.hover
        self.enabled = enabled
        super().config(bg=self.base, fg=self.fg if enabled else MUTED, cursor="hand2" if enabled else "arrow",
                       **({"text": text} if text is not None else {}))


class Popup:
    """Dark dropdown menu. items: ('header', text) | ('sep',) | ('item', text, checked, callback, keep_open)."""

    def __init__(self, app):
        self.app, self.win, self.anchor, self.build = app, None, None, None
        app.root.bind_all("<Button-1>", self._on_click, add="+")
        app.root.bind("<Escape>", lambda e: self.close(), add="+")

    def toggle(self, anchor, build):
        if self.win and self.anchor is anchor:
            return self.close()
        self.close()
        self.anchor, self.build = anchor, build
        self._render()

    def close(self):
        if self.win:
            self.win.destroy()
        self.win = self.anchor = None

    def _on_click(self, e):
        if self.win and e.widget is not self.anchor and not str(e.widget).startswith(str(self.win)):
            self.close()

    def _render(self):
        if self.win:
            self.win.destroy()
        w = tk.Toplevel(self.app.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=BORDER_LINE)
        inner = tk.Frame(w, bg=BG)
        inner.pack(padx=1, pady=1, fill="both")
        cols = [[]]
        for item in self.build():
            if item[0] == "col":
                cols.append([])
            else:
                cols[-1].append(item)
        for items in cols:
            col = tk.Frame(inner, bg=BG)
            col.pack(side="left", anchor="n")
            tk.Frame(col, bg=BG, width=230, height=1).pack()
            self._fill(col, items)
            tk.Frame(col, bg=BG, height=4).pack()
        w.update_idletasks()
        a = self.anchor
        rw, rh = w.winfo_reqwidth(), w.winfo_reqheight()
        mx, my, mw, mh = screen_for((a.winfo_rootx(), a.winfo_rooty(), 1, 1))
        x = min(a.winfo_rootx(), mx + mw - rw)
        y = a.winfo_rooty() + a.winfo_height() + 4
        if y + rh > my + mh:  # no room below: open upwards
            y = a.winfo_rooty() - rh - 4
        self.win = w
        place(w, x, max(y, my), rw, rh)

    def _fill(self, inner, items):
        for item in items:
            kind = item[0]
            if kind == "header":
                tk.Label(inner, text=item[1], bg=BG, fg=MUTED, font=(FONT, 9), anchor="w").pack(
                    fill="x", padx=14, pady=(8, 2))
            elif kind == "sep":
                tk.Frame(inner, bg=BORDER_LINE, height=1).pack(fill="x", pady=4)
            else:
                _, text, checked, cb, keep = item
                row = tk.Frame(inner, bg=BG, cursor="hand2")
                row.pack(fill="x")
                mark = tk.Label(row, text="\u2713" if checked else "", bg=BG, fg=FG, font=(SYMBOL, 10), width=2)
                mark.pack(side="left", padx=(8, 0), pady=3)
                lab = tk.Label(row, text=text, bg=BG, fg=FG, font=(FONT, 10), anchor="w")
                lab.pack(side="left", fill="x", expand=True, padx=(0, 16))
                for wdg in (row, mark, lab):
                    wdg.bind("<Enter>", lambda e, r=row, m=mark, l=lab: [x.config(bg=HOVER) for x in (r, m, l)])
                    wdg.bind("<Leave>", lambda e, r=row, m=mark, l=lab: [x.config(bg=BG) for x in (r, m, l)])
                    wdg.bind("<Button-1>", lambda e, cb=cb, keep=keep: self._pick(cb, keep))

    def _pick(self, cb, keep):
        if keep:
            if cb:
                cb()
            if self.win:
                self._render()
        else:
            self.close()
            if cb:
                cb()


def screen_for(rect):
    """(x, y, w, h) of the monitor containing the rect's center."""
    x, y, w, h = rect
    cx, cy = x + w // 2, y + h // 2
    if WIN:
        for mx, my, mw, mh in monitors():
            if mx <= cx < mx + mw and my <= cy < my + mh:
                return mx, my, mw, mh
    root = tk._default_root
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def fmt_hotkey(combo):
    return "+".join(p.upper() if len(p) == 1 else p.capitalize() for p in combo.split("+"))


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Capty")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        if WIN:
            self.root.overrideredirect(True)  # borderless toolbar; docks next to the selection

        self.cfg = load_config()
        self.selected = None
        self.manual_pos = False
        self.ffproc = None
        self.last_saved = None
        self.out_mp4 = self.out_gif = self.palette = None
        self.overlay = Overlay(self.root)
        self.state = "idle"  # idle | countdown | recording | stopping
        self.audio_selected = set()
        self.win_audio = None  # live Windows recorder while a recording is in progress
        self.lin_audio = {}  # Linux: ffmpeg filter index -> (device key, enabled)
        self.last_kind = {}  # kind -> keys that were on before the bar switched it off
        self.popup = Popup(self)

        self.outdir = tk.StringVar(value=self.cfg.get("outdir") or DEFAULT_DIR)
        self.delay = tk.IntVar(value=self.cfg.get("delay", 3))
        self.fmt = tk.StringVar(value=self.cfg.get("format", "mp4"))
        self.fps = tk.IntVar(value=self.cfg.get("fps", 30))
        self.prefix = tk.StringVar(value=self.cfg.get("prefix", "capture"))
        self.pointer = tk.BooleanVar(value=self.cfg.get("pointer", True))
        self.hotkeys = {**DEFAULT_HOTKEYS, **self.cfg.get("hotkeys", {})}
        self.status = tk.StringVar(value="Ready")

        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)
        row = tk.Frame(outer, bg=BG)
        row.pack(padx=8, pady=(8, 2))

        def sep():
            f = tk.Frame(row, bg=BORDER_LINE, width=1)
            f.pack(side="left", fill="y", padx=6, pady=4)
            return f

        if WIN:
            FlatButton(row, "\u2715", self.on_close, hover="#5a2a2e", fg=MUTED, font=(SYMBOL, 10), padx=9).pack(side="left")
            sep()
        self.area_btn = FlatButton(row, "\u2b1a  Area", self.on_select, font=(SYMBOL, 10))
        self.area_btn.pack(side="left")
        self.groups = {}  # kind -> (frame, toggle, dropdown)
        for kind, _on, _off, _title in KINDS:
            g = tk.Frame(row, bg=BG)
            tb = FlatButton(g, _on, lambda k=kind: self.toggle_kind(k), font=(EMOJI, 11), padx=8)
            dd = FlatButton(g, "\u25be", lambda k=kind: self.show_kind_menu(k, self.groups[k][2]),
                            font=(SYMBOL, 9), padx=4)
            tb.pack(side="left")
            dd.pack(side="left")
            self.groups[kind] = (g, tb, dd)
        self.sep2 = sep()
        self.opt_btn = FlatButton(row, "Options  \u25be", self.show_options)
        self.opt_btn.pack(side="left", padx=(0, 6))
        self.rec_btn = FlatButton(row, "\u25cf  Record", self.on_record_click, bg=ACCENT, hover=ACCENT_HOVER,
                                  fg="white", font=(FONT, 10, "bold"), width=11)
        self.rec_btn.pack(side="left")
        self.status_lbl = tk.Label(outer, textvariable=self.status, bg=BG, fg=MUTED, font=(FONT, 8), width=1)
        self.status_lbl.pack(fill="x", padx=8, pady=(0, 6))
        self.status_lbl.bind("<Button-1>", lambda e: self.open_folder())
        for wdg in (outer, row, self.status_lbl):  # drag the toolbar by any empty area
            wdg.bind("<ButtonPress-1>", self._drag_start, add="+")
            wdg.bind("<B1-Motion>", self._drag_move, add="+")

        self.audio_vars = {}
        self.audio_devs = []
        self.refresh_audio()
        if WIN and not pyaudio:
            self.status.set("No audio: pip install PyAudioWPatch")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._bound = {}
        if WIN:
            self._start_hotkey_thread()
        self.apply_hotkeys()
        self.root.update()
        self.dock()
        self.style_window()

    HK_ACTIONS = {"record": "on_record", "stop": "stop"}

    def style_window(self):
        """Windows 11: rounded corners and a subtle border on the borderless toolbar."""
        if not WIN:
            return
        try:
            hwnd = ctypes.c_void_p(ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id())
            dwm = ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)  # DWMWCP_ROUND
            dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(ctypes.c_int(0x0040403A)), 4)  # border colour (BGR)
        except Exception:
            pass

    def dock(self):
        """Windows: put the toolbar under the selection (or above / inside if no room); else bottom-centre."""
        if not WIN or self.manual_pos:
            return
        self.root.update_idletasks()
        bw, bh = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        gap = 8
        if self.selected:
            x, y, w, h = self.selected
            mx, my, mw, mh = screen_for(self.selected)
            px = min(max(x + w - bw, mx), mx + mw - bw)  # right-aligned with the selection, kept on screen
            below, above = y + h + BORDER + gap, y - BORDER - gap - bh
            if below + bh <= my + mh:
                py = below
            elif above >= my:
                py = above
            else:
                py = my + mh - bh - gap  # no room outside: dock inside the bottom edge
        else:
            mx, my, mw, mh = next((m for m in monitors() if m[0] == 0 and m[1] == 0), monitors()[0])
            px, py = mx + (mw - bw) // 2, my + mh - bh - 80
        place(self.root, px, py, bw, bh)

    def _drag_start(self, e):
        if WIN:
            self._drag = (e.x_root - self.root.winfo_rootx(), e.y_root - self.root.winfo_rooty())

    def _drag_move(self, e):
        if WIN and getattr(self, "_drag", None):
            self.manual_pos = True
            place(self.root, e.x_root - self._drag[0], e.y_root - self._drag[1],
                  self.root.winfo_width(), self.root.winfo_height())

    def apply_hotkeys(self):
        """Window-local bindings everywhere; on Windows also global (RegisterHotKey)."""
        for seq in self._bound.values():
            self.root.unbind(seq)
        self._bound = {}
        for action, combo in self.hotkeys.items():
            seq = tk_sequence(combo)
            if seq:
                self.root.bind(seq, lambda e, a=action: getattr(self, self.HK_ACTIONS[a])())
                self._bound[action] = seq
        if WIN:
            ctypes.windll.user32.PostThreadMessageW(self._hk_tid, WM_APP, 0, 0)

    def _start_hotkey_thread(self):
        ready = threading.Event()

        def loop():
            u32 = ctypes.windll.user32
            msg = ctypes.wintypes.MSG()
            u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create this thread's message queue
            self._hk_tid = ctypes.windll.kernel32.GetCurrentThreadId()
            ready.set()
            ids = {}
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_APP:  # (re)register from current settings
                    for hid in ids:
                        u32.UnregisterHotKey(None, hid)
                    ids = {}
                    for n, (action, combo) in enumerate(self.hotkeys.items(), 1):
                        parsed = parse_hotkey(combo)
                        if parsed and u32.RegisterHotKey(None, n, parsed[0] | MOD_NOREPEAT, parsed[1]):
                            ids[n] = action
                        elif parsed:
                            self.set_status(f"Global key {combo} unavailable (in use?)")
                elif msg.message == WM_HOTKEY and msg.wParam in ids:
                    self.root.after(0, getattr(self, self.HK_ACTIONS[ids[msg.wParam]]))

        threading.Thread(target=loop, daemon=True).start()
        ready.wait()

    def capture_hotkey(self, action):
        self.status.set(f"Press new {action} shortcut... (Esc cancels)")
        win_alt = 0x20000 if WIN else 0x8

        def on_key(e):
            if e.keysym in MODIFIER_KEYSYMS:
                return "break"
            self.root.unbind("<KeyPress>", bind_id)
            self.status.set("Ready")
            if e.keysym != "Escape":
                mods = [n for n, m in (("ctrl", 0x4), ("alt", win_alt), ("shift", 0x1)) if e.state & m]
                combo = "+".join(mods + [e.keysym.lower()])
                if parse_hotkey(combo) and (mods or e.keysym.lower().startswith("f")):
                    self.hotkeys[action] = combo
                    self.apply_hotkeys()
                    self.save_settings()
                    self.status.set(f"{action.capitalize()}: {fmt_hotkey(combo)}")
                else:
                    self.status.set("Use Ctrl/Alt/Shift + a letter, digit or F-key")
            return "break"

        bind_id = self.root.bind("<KeyPress>", on_key, add="+")
        self.root.focus_force()

    def refresh_audio(self):
        """(Re)list audio sources; keeps checked state, so plugged-in mics can be picked up."""
        chosen = set(self.cfg.get("audio", [])) | {k for k, v in self.audio_vars.items() if v.get()}
        self.audio_devs = list_audio_devices()
        self.audio_vars = {d["key"]: tk.BooleanVar(value=d["key"] in chosen) for d in self.audio_devs}
        for v in self.audio_vars.values():
            v.trace_add("write", lambda *_: self.on_audio_change())
        self.audio_selected = {k for k, v in self.audio_vars.items() if v.get()}
        self.sync_bar_audio()

    def on_audio_change(self):
        """A source was switched on/off (main window, bar or menu); applies live while recording."""
        old = self.audio_selected
        self.audio_selected = {k for k, v in self.audio_vars.items() if v.get()}
        if self.audio_selected == old:
            return
        self.save_settings()
        self.sync_bar_audio()
        if self.win_audio:
            self.win_audio.apply(self.audio_selected)
        elif self.lin_audio and self.ffproc:
            for i, (key, was) in list(self.lin_audio.items()):
                want = key in self.audio_selected
                if want != was:
                    try:  # ffmpeg's interactive command: retune the volume filter of that input
                        self.ffproc.stdin.write(f"cvolume@a{i} -1 volume {int(want)}\n".encode())
                        self.ffproc.stdin.flush()
                        self.lin_audio[i] = (key, want)
                    except OSError as e:
                        print("Audio switch error:", e)

    def sync_bar_audio(self):
        for kind, on_icon, off_icon, _title in KINDS:
            g, tb, dd = self.groups[kind]
            keys = [d["key"] for d in self.audio_devs if d["kind"] == kind]
            if not keys:
                g.pack_forget()
                continue
            on = any(k in self.audio_selected for k in keys)
            tb.look(bg=ON if on else OFF, hover="#3fb85f" if on else HOVER, text=on_icon if on else off_icon)
            dd.look(bg=ON if on else OFF, hover="#3fb85f" if on else HOVER)
            g.pack(side="left", padx=3, before=self.sep2)
        self.dock()

    def toggle_kind(self, kind):
        """Bar button: switch all mics / all system audio off, or back to what was on (default: first device)."""
        keys = [d["key"] for d in self.audio_devs if d["kind"] == kind]
        on = [k for k in keys if k in self.audio_selected]
        if on:
            self.last_kind[kind] = on
            target = set()
        else:
            target = set(self.last_kind.get(kind) or keys[:1])
        for k in keys:
            self.audio_vars[k].set(k in target)

    def show_kind_menu(self, kind, widget):
        title = next(t for k, _a, _b, t in KINDS if k == kind)

        def build():
            items = [("header", title)]
            for d in self.audio_devs:
                if d["kind"] == kind:
                    var = self.audio_vars[d["key"]]
                    items.append(("item", d["label"].split(": ", 1)[1], var.get(),
                                  lambda v=var: v.set(not v.get()), True))
            items += [("sep",), ("item", "Refresh devices", None, self.refresh_audio, False)]
            return items
        self.popup.toggle(widget, build)

    def show_options(self):
        def pick(var, value):
            return lambda: (var.set(value), self.save_settings())

        def choices(var, options, fmt):
            vals = list(options) + ([var.get()] if var.get() not in options else [])
            return [("item", fmt(v), var.get() == v, pick(var, v), False) for v in vals]

        def build():
            cur = self.outdir.get().strip() or DEFAULT_DIR
            items = [("header", "Save to"),
                     ("item", os.path.basename(cur.rstrip("/\\")) or cur, True, self.open_folder, False),
                     ("item", "Other location...", None, self.on_browse, False),
                     ("sep",), ("header", "Timer")]
            items += choices(self.delay, (0, 3, 5, 10), lambda v: "None" if v == 0 else f"{v} seconds")
            items += [("sep",), ("header", "Format")]
            items += choices(self.fmt, ("mp4", "gif"), lambda v: "MP4 video" if v == "mp4" else "GIF animation")
            items += [("col",), ("header", "Frame rate")]
            items += choices(self.fps, (15, 24, 30, 60), lambda v: f"{v} fps")
            items += [("sep",), ("header", "Options"),
                      ("item", "Show mouse pointer", self.pointer.get(),
                       lambda: (self.pointer.set(not self.pointer.get()), self.save_settings()), True),
                      ("item", "File name prefix...", None, self.ask_prefix, False)]
            if self.selected:
                items.append(("item", "Clear selection", None, self.on_clear, False))
            items += [("sep",), ("header", "Shortcuts")]
            for action in ("record", "stop"):
                items.append(("item", f"{action.capitalize()}   {fmt_hotkey(self.hotkeys[action])}", None,
                              lambda a=action: self.capture_hotkey(a), False))
            return items
        self.popup.toggle(self.opt_btn, build)

    def ask_prefix(self):
        v = simpledialog.askstring("File name prefix", "Recordings are named <prefix>-<date and time>:",
                                   initialvalue=self.prefix.get(), parent=self.root)
        if v and v.strip():
            self.prefix.set(v.strip())
            self.save_settings()

    def open_folder(self):
        path = self.last_saved or self.outdir.get().strip() or DEFAULT_DIR
        try:
            if WIN:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)] if os.path.isfile(path)
                                 else ["explorer", os.path.normpath(path)])
            else:
                subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
        except OSError as e:
            print("Open folder error:", e)

    def save_settings(self):
        try:
            self.cfg.update(outdir=self.outdir.get().strip(), delay=self.delay.get(),
                            fps=self.fps.get(), format=self.fmt.get(), hotkeys=self.hotkeys,
                            prefix=self.prefix.get(), pointer=self.pointer.get(),
                            audio=[k for k, v in self.audio_vars.items() if v.get()])
        except tk.TclError:  # spinbox holds non-numeric text
            return
        save_config(self.cfg)

    def on_close(self):
        self.save_settings()
        self.root.destroy()

    def on_browse(self):
        d = filedialog.askdirectory(initialdir=self.outdir.get() or DEFAULT_DIR, title="Save recordings to")
        if d:
            self.outdir.set(os.path.normpath(d))
            self.last_saved = None
            self.save_settings()

    def set_status(self, s):
        self.root.after(0, self.status.set, s)

    def on_select(self):
        self.overlay.hide()
        if WIN:
            self.root.withdraw()
            self.root.update()
            rect = select_area(self.root)
            self.root.deiconify()
        else:
            rect = select_area_slop()
        if not rect:
            self.status.set("Selection cancelled")
            if self.selected:
                self.overlay.show(self.selected)
            self.dock()
            return
        self.selected = rect
        self.manual_pos = False
        self.overlay.show(rect)
        self.dock()
        self.status.set(f"{rect[2]}\u00d7{rect[3]} selected")

    def on_clear(self):
        self.selected = None
        self.overlay.hide()
        self.manual_pos = False
        self.dock()
        self.status.set("Selection cleared")

    def on_record(self):
        if self.state != "idle":  # already recording / counting down
            return
        if not self.selected:
            self.on_select()  # no area yet: let the user pick one, then carry on recording
            if not self.selected:
                return
        name = f"{self.prefix.get().strip() or 'capture'}-{time.strftime('%Y-%m-%d-%H-%M-%S')}"
        if not shutil.which("ffmpeg"):
            self.status.set("ffmpeg not found in PATH")
            return

        outdir = self.outdir.get().strip() or DEFAULT_DIR
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            self.status.set(f"Cannot use folder: {e}")
            return
        self.save_settings()
        base = os.path.join(outdir, name)
        if any(os.path.exists(base + s) for s in (".mp4", ".gif", "_palette.png")):
            base += time.strftime("-%Y-%m-%d-%H-%M-%S")
        self.out_mp4, self.out_gif, self.palette = base + ".mp4", base + ".gif", base + "_palette.png"

        x, y, w, h = self.selected
        w, h = w & ~1, h & ~1  # yuv420p needs even dimensions
        fps = self.fps.get()
        delay = self.delay.get()
        to_gif = self.fmt.get() == "gif"
        if WIN:
            grab = ["-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", str(int(self.pointer.get())),
                    "-offset_x", str(x), "-offset_y", str(y),
                    "-video_size", f"{w}x{h}", "-i", "desktop"]
        else:
            display = os.environ.get("DISPLAY", ":0")
            if "." not in display:
                display += ".0"
            grab = ["-f", "x11grab", "-framerate", str(fps), "-draw_mouse", str(int(self.pointer.get())),
                    "-video_size", f"{w}x{h}", "-i", f"{display}+{x},{y}"]
        audio_in, audio_out = [], []
        use_audio = not to_gif and bool(self.audio_devs)
        self.lin_audio = {}
        win_audio = None
        if use_audio and WIN and pyaudio:
            win_audio = WinAudioRecorder(self.audio_devs, os.path.splitext(self.out_mp4)[0])
        elif use_audio and not WIN and self.audio_selected:
            # ffmpeg can't add inputs mid-recording, so every source is wired in and gated with a volume filter
            devs = self.audio_devs
            chains = []
            for i, d in enumerate(devs):
                audio_in += ["-f", "pulse", "-i", d["name"]]
                on = d["key"] in self.audio_selected
                chains.append(f"[{i + 1}:a]volume@a{i}={int(on)}[s{i}]")
                self.lin_audio[i] = (d["key"], on)
            mix = "".join(f"[s{i}]" for i in range(len(devs))) + f"amix=inputs={len(devs)}:duration=longest:normalize=0[a]"
            audio_out = ["-filter_complex", ";".join(chains + [mix]), "-map", "0:v", "-map", "[a]",
                         "-c:a", "aac", "-b:a", "192k", "-ac", "2"]
        self.win_audio = None
        cmd = [
            "ffmpeg", "-y", *grab, *audio_in,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p", *audio_out,
            self.out_mp4,
        ]

        self.status.set(f"Starting in {delay}s..." if delay else "Starting...")
        self.state, self.t0, self.delay_s = "countdown", time.time(), delay
        self.tick()

        def worker():
            try:
                time.sleep(delay)
                self.ffproc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
                self.root.after(0, self._rec_started)
                if win_audio:
                    win_audio.start(self.audio_selected)
                    self.win_audio = win_audio
                self.ffproc.wait()
                self.win_audio = None
                self.ffproc = None
                if win_audio:
                    self.set_status("Adding audio...")
                    try:
                        wavs = win_audio.stop()
                        if wavs:
                            # ffmpeg takes a moment to start grabbing; skip the audio recorded before the video began
                            video_start = self.t_stop - video_duration(self.out_mp4)
                            mux_audio(self.out_mp4, wavs, max(0.0, video_start - win_audio.t0))
                    except Exception as e:
                        print("Audio mux error:", e)
                        self.set_status("Saved video, but adding audio failed")
                self.root.after(0, self.on_finished, to_gif, fps)
            except Exception as e:
                print("Recording error:", e)
                self.ffproc = None
                self.set_status(f"Error: {e}")
                self.root.after(0, self._reset_buttons)

        threading.Thread(target=worker, daemon=True).start()

    def _rec_started(self):
        self.state, self.t0 = "recording", time.time()
        self.status.set("Recording...")

    def tick(self):
        """Refresh the record button: countdown, then elapsed time."""
        if self.state == "idle":
            return
        self._render_state()
        self.root.after(250, self.tick)

    def _render_state(self):
        if self.state == "countdown":
            left = max(0, int(self.delay_s - (time.time() - self.t0) + 0.999))
            self.rec_btn.look(bg="#4a4a50", hover="#4a4a50", text=f"{left}", enabled=False)
        elif self.state == "recording":
            e = int(time.time() - self.t0)
            self.rec_btn.look(bg="#4a4a50", hover="#5e5e66", text=f"\u25a0  {e // 60:02d}:{e % 60:02d}")
        elif self.state == "stopping":
            self.rec_btn.look(bg="#4a4a50", hover="#4a4a50", text="Saving...", enabled=False)
        else:
            self.rec_btn.look(bg=ACCENT, hover=ACCENT_HOVER, text="\u25cf  Record")
        self.area_btn.look(enabled=self.state == "idle")

    def on_record_click(self):
        if self.state == "idle":
            self.on_record()
        elif self.state == "recording":
            self.stop()

    def stop(self):
        p = self.ffproc
        if not p:
            self.status.set("Not recording")
            return
        self.t_stop = time.time()
        try:
            p.stdin.write(b"q")  # ffmpeg finalizes the file on 'q'
            p.stdin.flush()
            self.status.set("Stopping...")
            self.state = "stopping"
        except Exception as e:
            print("Stop error:", e)
            p.terminate()

    def _reset_buttons(self):
        self.state = "idle"
        self._render_state()

    def on_finished(self, to_gif, fps):
        self._reset_buttons()
        if not to_gif:
            self.last_saved = self.out_mp4
            self.status.set(f"Saved {os.path.basename(self.out_mp4)}  \u00b7  click to show")
            return
        self.status.set("Converting to GIF...")

        def convert():
            try:
                kw = dict(check=True, creationflags=NO_WINDOW,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["ffmpeg", "-y", "-i", self.out_mp4,
                                "-vf", f"fps={fps},scale=iw:-1:flags=lanczos,palettegen",
                                self.palette], **kw)
                subprocess.run(["ffmpeg", "-y", "-i", self.out_mp4, "-i", self.palette,
                                "-filter_complex", f"fps={fps},scale=iw:-1:flags=lanczos[x];[x][1:v]paletteuse",
                                self.out_gif], **kw)
                if shutil.which("gifsicle"):
                    subprocess.run(["gifsicle", "-O3", self.out_gif, "-o", self.out_gif], **kw)
                os.remove(self.palette)
                self.last_saved = self.out_gif
                self.set_status(f"Saved {os.path.basename(self.out_gif)}  \u00b7  click to show")
            except Exception as e:
                print("GIF conversion error:", e)
                self.set_status("GIF conversion failed")

        threading.Thread(target=convert, daemon=True).start()

    def run(self):
        self.root.mainloop()


def main():
    if "--install" in sys.argv:
        if not WIN:
            sys.exit("--install is Windows-only; use the .deb on Linux")
        install_start_menu()
        return
    App().run()


if __name__ == "__main__":
    main()

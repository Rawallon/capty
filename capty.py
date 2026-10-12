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
from tkinter import filedialog, ttk

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
    """Records each chosen source to its own WAV (silence-padded so it stays on the video timeline)."""

    def __init__(self, devices, base):
        self.devices = devices
        self.base = base
        self.streams = []  # (stream, wavefile, state, path)

    def start(self):
        self.p = pyaudio.PyAudio()
        self.t0 = time.time()
        for n, dev in enumerate(self.devices):
            path = f"{self.base}_audio{n}.wav"
            try:
                wf = wave.open(path, "wb")
                wf.setnchannels(dev["channels"])
                wf.setsampwidth(2)
                wf.setframerate(dev["rate"])
                st = {"written": 0, "rate": dev["rate"], "ch": dev["channels"]}
                stream = self.p.open(format=pyaudio.paInt16, channels=dev["channels"], rate=dev["rate"],
                                     input=True, input_device_index=dev["index"], frames_per_buffer=1024,
                                     stream_callback=self._callback(wf, st))
                self.streams.append((stream, wf, st, path))
            except Exception as e:
                print(f"Audio source {dev['label']} failed:", e)

    def _callback(self, wf, st):
        def cb(data, frames, _ti, _status):
            # loopback delivers nothing while silent: fill the gap so audio stays in sync
            gap = int((time.time() - self.t0) * st["rate"]) - st["written"] - frames
            if gap > st["rate"] // 5:
                wf.writeframes(bytes(gap * st["ch"] * 2))
                st["written"] += gap
            wf.writeframes(data)
            st["written"] += frames
            return None, pyaudio.paContinue
        return cb

    def stop(self):
        """Returns the WAV paths that were recorded."""
        total = time.time() - self.t0
        paths = []
        for stream, wf, st, path in self.streams:
            try:
                stream.stop_stream()
                stream.close()
                deficit = int(total * st["rate"]) - st["written"]
                if deficit > 0:
                    wf.writeframes(bytes(deficit * st["ch"] * 2))
            finally:
                wf.close()
            paths.append(path)
        self.streams = []
        self.p.terminate()
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


class ControlBar:
    """Small floating Record/Stop bar docked next to the selection (outside the captured area)."""
    GAP = 8

    def __init__(self, root, on_click):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#202020")
        self.win.withdraw()
        self.btn = tk.Button(self.win, text="● Record", command=on_click, bg="#d9232d", fg="white",
                             activebackground="#ff3b45", activeforeground="white", relief="flat",
                             font=("Segoe UI" if WIN else "TkDefaultFont", 10, "bold"), padx=12, pady=4, bd=0)
        self.btn.pack(side="left", padx=(8, 6), pady=8)
        self.label = tk.Label(self.win, text="", bg="#202020", fg="white", width=7,
                              font=("Segoe UI" if WIN else "TkDefaultFont", 10))
        self.label.pack(side="left", padx=(0, 10))
        self.win.update_idletasks()
        self.size = (self.win.winfo_reqwidth(), self.win.winfo_reqheight())

    def _bounds(self, rect):
        """Screen rect containing the selection's center."""
        x, y, w, h = rect
        cx, cy = x + w // 2, y + h // 2
        if WIN:
            for mx, my, mw, mh in monitors():
                if mx <= cx < mx + mw and my <= cy < my + mh:
                    return mx, my, mw, mh
        return 0, 0, self.win.winfo_screenwidth(), self.win.winfo_screenheight()

    def show(self, rect):
        x, y, w, h = rect
        bw, bh = self.size
        mx, my, mw, mh = self._bounds(rect)
        px = min(max(x + w - bw, mx), mx + mw - bw)  # right-aligned with the selection, kept on screen
        below = y + h + BORDER + self.GAP
        above = y - BORDER - self.GAP - bh
        if below + bh <= my + mh:
            py = below
        elif above >= my:
            py = above
        else:
            py = my + mh - bh - self.GAP  # no room outside: dock inside the bottom edge
        self.win.deiconify()
        place(self.win, px, py, bw, bh)

    def hide(self):
        self.win.withdraw()

    def update(self, state, text=""):
        if state == "recording":
            self.btn.config(text="■ Stop", bg="#444444", activebackground="#666666", state="normal")
        elif state == "countdown":
            self.btn.config(text="● Record", bg="#d9232d", state="disabled")
        elif state == "stopping":
            self.btn.config(text="Saving...", bg="#444444", state="disabled")
        else:
            self.btn.config(text="● Record", bg="#d9232d", activebackground="#ff3b45", state="normal")
        self.label.config(text=text)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Capty")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        self.cfg = load_config()
        self.selected = None
        self.ffproc = None
        self.out_mp4 = self.out_gif = self.palette = None
        self.overlay = Overlay(self.root)
        self.state = "idle"  # idle | countdown | recording | stopping
        self.bar = ControlBar(self.root, self.on_bar_click)

        f = ttk.Frame(self.root, padding=10)
        f.pack()

        row = ttk.Frame(f)
        row.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        self.select_btn = ttk.Button(row, text="Select area", command=self.on_select)
        self.select_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.clear_btn = ttk.Button(row, text="Clear", command=self.on_clear, state="disabled")
        self.clear_btn.pack(side="left", expand=True, fill="x")

        ttk.Label(f, text="Filename:").grid(row=2, column=0, sticky="w")
        self.fname = tk.StringVar(value=time.strftime("capture--%Y-%m-%d-%H-%M-%S"))
        ttk.Entry(f, textvariable=self.fname).grid(row=2, column=1, columnspan=2, sticky="ew", pady=2)

        ttk.Label(f, text="Save to:").grid(row=2, column=0, sticky="w")
        self.outdir = tk.StringVar(value=self.cfg.get("outdir") or DEFAULT_DIR)
        ttk.Entry(f, textvariable=self.outdir, width=34).grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Button(f, text="Browse...", command=self.on_browse).grid(row=2, column=2, padx=(4, 0))

        ttk.Label(f, text="Delay (s):").grid(row=3, column=0, sticky="w")
        self.delay = tk.IntVar(value=self.cfg.get("delay", 3))
        ttk.Spinbox(f, from_=0, to=60, textvariable=self.delay, width=6).grid(row=3, column=1, sticky="w", pady=2)

        ttk.Label(f, text="Format:").grid(row=4, column=0, sticky="w")
        self.fmt = tk.StringVar(value=self.cfg.get("format", "mp4"))
        fr = ttk.Frame(f)
        fr.grid(row=4, column=1, columnspan=2, sticky="w", pady=2)
        ttk.Radiobutton(fr, text="MP4 (video)", variable=self.fmt, value="mp4").pack(side="left")
        ttk.Radiobutton(fr, text="GIF (animated)", variable=self.fmt, value="gif").pack(side="left", padx=(8, 0))

        ttk.Label(f, text="FPS:").grid(row=5, column=0, sticky="w")
        self.fps = tk.IntVar(value=self.cfg.get("fps", 30))
        ttk.Spinbox(f, from_=1, to=240, textvariable=self.fps, width=6).grid(row=5, column=1, sticky="w", pady=2)

        ttk.Label(f, text="Audio:").grid(row=6, column=0, sticky="nw")
        self.audio_frame = ttk.Frame(f)
        self.audio_frame.grid(row=6, column=1, columnspan=2, sticky="w", pady=2)
        self.audio_vars = {}
        self.audio_devs = []
        self.refresh_audio()

        self.hotkeys = {**DEFAULT_HOTKEYS, **self.cfg.get("hotkeys", {})}
        self.hk_vars = {}
        for i, (action, label) in enumerate((("record", "Record key:"), ("stop", "Stop key:"))):
            ttk.Label(f, text=label).grid(row=7 + i, column=0, sticky="w")
            var = tk.StringVar(value=self.hotkeys[action])
            self.hk_vars[action] = var
            ttk.Entry(f, textvariable=var, state="readonly", width=34).grid(row=7 + i, column=1, sticky="ew", pady=2)
            ttk.Button(f, text="Set...", command=lambda a=action: self.capture_hotkey(a)).grid(
                row=7 + i, column=2, padx=(4, 0))

        row = ttk.Frame(f)
        row.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        self.record_btn = ttk.Button(row, text="Record", command=self.on_record)
        self.record_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.stop_btn = ttk.Button(row, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x")

        self.status = tk.StringVar(value="Ready")
        ttk.Label(f, textvariable=self.status).grid(row=10, column=0, columnspan=3)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._bound = {}
        if WIN:
            self._start_hotkey_thread()
        self.apply_hotkeys()

    HK_ACTIONS = {"record": "on_record", "stop": "stop"}

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
        var = self.hk_vars[action]
        var.set("Press keys... (Esc cancels)")
        old = self.hotkeys[action]
        win_alt = 0x20000 if WIN else 0x8

        def on_key(e):
            if e.keysym in MODIFIER_KEYSYMS:
                return "break"
            self.root.unbind("<KeyPress>", bind_id)
            if e.keysym != "Escape":
                mods = [n for n, m in (("ctrl", 0x4), ("alt", win_alt), ("shift", 0x1)) if e.state & m]
                combo = "+".join(mods + [e.keysym.lower()])
                if parse_hotkey(combo) and (mods or e.keysym.lower().startswith("f")):
                    self.hotkeys[action] = combo
                    self.apply_hotkeys()
                    self.save_settings()
                else:
                    self.status.set("Use Ctrl/Alt/Shift + a letter, digit or F-key")
            var.set(self.hotkeys[action])
            return "break"

        bind_id = self.root.bind("<KeyPress>", on_key, add="+")
        self.root.focus_force()

    def refresh_audio(self):
        """(Re)list audio sources; keeps checked state, so plugged-in mics can be picked up."""
        for w in self.audio_frame.winfo_children():
            w.destroy()
        chosen = set(self.cfg.get("audio", [])) | {k for k, v in self.audio_vars.items() if v.get()}
        self.audio_devs = list_audio_devices()
        self.audio_vars = {d["key"]: tk.BooleanVar(value=d["key"] in chosen) for d in self.audio_devs}
        if WIN and not pyaudio:
            ttk.Label(self.audio_frame, text="No audio: pip install PyAudioWPatch").pack(anchor="w")
        elif not self.audio_devs:
            ttk.Label(self.audio_frame, text="No audio devices found").pack(anchor="w")
        for d in self.audio_devs:
            ttk.Checkbutton(self.audio_frame, text=d["label"], variable=self.audio_vars[d["key"]],
                            command=self.save_settings).pack(anchor="w")
        ttk.Button(self.audio_frame, text="Refresh devices", command=self.refresh_audio).pack(anchor="w", pady=(4, 0))

    def save_settings(self):
        try:
            self.cfg.update(outdir=self.outdir.get().strip(), delay=self.delay.get(),
                            fps=self.fps.get(), format=self.fmt.get(), hotkeys=self.hotkeys,
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
            self.save_settings()

    def set_status(self, s):
        self.root.after(0, self.status.set, s)

    def on_select(self):
        self.overlay.hide()
        self.bar.hide()
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
                self.bar.show(self.selected)
            return
        self.selected = rect
        self.overlay.show(rect)
        self.bar.show(rect)
        self.clear_btn.config(state="normal")
        x, y, w, h = rect
        self.status.set(f"Selected: {x},{y} {w}x{h}")

    def on_clear(self):
        self.selected = None
        self.overlay.hide()
        self.bar.hide()
        self.clear_btn.config(state="disabled")
        self.status.set("Selection cleared")

    def on_record(self):
        if str(self.record_btn["state"]) == "disabled":  # already recording / counting down
            return
        if not self.selected:
            self.on_select()  # no area yet: let the user pick one, then carry on recording
            if not self.selected:
                return
        name = self.fname.get().strip()
        if not name:
            self.status.set("Please enter filename")
            return
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
            grab = ["-f", "gdigrab", "-framerate", str(fps),
                    "-offset_x", str(x), "-offset_y", str(y),
                    "-video_size", f"{w}x{h}", "-i", "desktop"]
        else:
            display = os.environ.get("DISPLAY", ":0")
            if "." not in display:
                display += ".0"
            grab = ["-f", "x11grab", "-framerate", str(fps),
                    "-video_size", f"{w}x{h}", "-i", f"{display}+{x},{y}"]
        audio = [] if to_gif else [d for d in self.audio_devs if self.audio_vars[d["key"]].get()]
        audio_in, audio_out = [], []
        if audio and not WIN:  # PulseAudio sources go straight into the same ffmpeg
            for d in audio:
                audio_in += ["-f", "pulse", "-i", d["name"]]
            if len(audio) == 1:
                audio_out = ["-map", "0:v", "-map", "1:a"]
            else:
                ins = "".join(f"[{i + 1}:a]" for i in range(len(audio)))
                audio_out = ["-filter_complex", f"{ins}amix=inputs={len(audio)}:duration=longest:normalize=0[a]",
                             "-map", "0:v", "-map", "[a]"]
            audio_out += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
        win_audio = WinAudioRecorder(audio, os.path.splitext(self.out_mp4)[0]) if audio and WIN else None
        cmd = [
            "ffmpeg", "-y", *grab, *audio_in,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p", *audio_out,
            self.out_mp4,
        ]

        self.record_btn.config(state="disabled")
        self.select_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status.set(f"Starting in {delay}s...")
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
                    win_audio.start()
                self.ffproc.wait()
                self.ffproc = None
                if win_audio:
                    self.set_status("Adding audio...")
                    try:
                        wavs = win_audio.stop() if win_audio.streams else []
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
        """Refresh the control bar: countdown, then elapsed time."""
        if self.state == "countdown":
            left = max(0, int(self.delay_s - (time.time() - self.t0) + 0.999))
            self.bar.update("countdown", f"{left}s")
        elif self.state == "recording":
            e = int(time.time() - self.t0)
            self.bar.update("recording", f"{e // 60:02d}:{e % 60:02d}")
        elif self.state == "stopping":
            self.bar.update("stopping")
        else:
            return
        self.root.after(250, self.tick)

    def on_bar_click(self):
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
        self.bar.update("idle")
        self.record_btn.config(state="normal")
        self.select_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def on_finished(self, to_gif, fps):
        self._reset_buttons()
        if not to_gif:
            self.status.set(f"Saved MP4: {self.out_mp4}")
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
                self.set_status(f"Saved GIF: {self.out_gif}")
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

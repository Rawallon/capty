#!/usr/bin/env python3
"""Capty: area screen recorder (Linux: x11grab + slop, Windows: gdigrab). tkinter UI."""
import os
import sys
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk

WIN = sys.platform == "win32"
if WIN:
    import ctypes
    import ctypes.wintypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor: tk + gdigrab use physical pixels
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Videos")
os.makedirs(DEFAULT_DIR, exist_ok=True)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
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


def select_area(root):
    """Windows: fullscreen dim overlay; drag to select. Returns (x, y, w, h) or None."""
    vx, vy, vw, vh = virtual_screen()
    top = tk.Toplevel(root)
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    top.attributes("-alpha", 0.3)
    top.configure(bg="black", cursor="crosshair")
    top.geometry(f"{vw}x{vh}{vx:+d}{vy:+d}")
    canvas = tk.Canvas(top, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    state = {"start": None, "rect": None, "result": None}

    def press(e):
        state["start"] = (e.x_root, e.y_root)
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline=BORDER_COLOR, width=2, fill="white")

    def drag(e):
        if state["start"]:
            sx, sy = state["start"]
            canvas.coords(state["rect"], sx - vx, sy - vy, e.x_root - vx, e.y_root - vy)

    def release(e):
        if state["start"]:
            sx, sy = state["start"]
            x, y = min(sx, e.x_root), min(sy, e.y_root)
            w, h = abs(e.x_root - sx), abs(e.y_root - sy)
            if w > 1 and h > 1:
                state["result"] = (x, y, w, h)
        top.destroy()

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", release)
    top.bind("<Escape>", lambda e: top.destroy())
    top.focus_force()
    root.wait_window(top)
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
            win.geometry(f"{gw}x{gh}{gx:+d}{gy:+d}")
            win.deiconify()

    def hide(self):
        for w in self.wins:
            w.withdraw()


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Capty")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        self.selected = None
        self.ffproc = None
        self.out_mp4 = self.out_gif = self.palette = None
        self.overlay = Overlay(self.root)

        f = ttk.Frame(self.root, padding=10)
        f.pack()

        row = ttk.Frame(f)
        row.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        self.select_btn = ttk.Button(row, text="Select area", command=self.on_select)
        self.select_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.clear_btn = ttk.Button(row, text="Clear", command=self.on_clear, state="disabled")
        self.clear_btn.pack(side="left", expand=True, fill="x")

        ttk.Label(f, text="Filename:").grid(row=1, column=0, sticky="w")
        self.fname = tk.StringVar(value=time.strftime("capture--%Y-%m-%d-%H-%M-%S"))
        ttk.Entry(f, textvariable=self.fname).grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)

        ttk.Label(f, text="Delay (s):").grid(row=2, column=0, sticky="w")
        self.delay = tk.IntVar(value=3)
        ttk.Spinbox(f, from_=0, to=60, textvariable=self.delay, width=6).grid(row=2, column=1, sticky="w", pady=2)

        ttk.Label(f, text="Format:").grid(row=3, column=0, sticky="w")
        self.fmt = tk.StringVar(value="mp4")
        fr = ttk.Frame(f)
        fr.grid(row=3, column=1, columnspan=2, sticky="w", pady=2)
        ttk.Radiobutton(fr, text="MP4 (video)", variable=self.fmt, value="mp4").pack(side="left")
        ttk.Radiobutton(fr, text="GIF (animated)", variable=self.fmt, value="gif").pack(side="left", padx=(8, 0))

        ttk.Label(f, text="FPS:").grid(row=4, column=0, sticky="w")
        self.fps = tk.IntVar(value=30)
        ttk.Spinbox(f, from_=1, to=240, textvariable=self.fps, width=6).grid(row=4, column=1, sticky="w", pady=2)

        row = ttk.Frame(f)
        row.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        self.record_btn = ttk.Button(row, text="Record", command=self.on_record)
        self.record_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.stop_btn = ttk.Button(row, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x")

        self.status = tk.StringVar(value="Ready")
        ttk.Label(f, textvariable=self.status).grid(row=6, column=0, columnspan=3)

        self.root.bind("<Control-Alt-s>", lambda e: self.stop())
        if WIN:
            self._start_hotkey()

    def _start_hotkey(self):
        """Windows-only global Ctrl+Alt+S via RegisterHotKey (works while another window has focus)."""
        def loop():
            u32 = ctypes.windll.user32
            if not u32.RegisterHotKey(None, 1, 0x0002 | 0x0001 | 0x4000, ord("S")):  # CTRL|ALT|NOREPEAT
                return
            msg = ctypes.wintypes.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    self.root.after(0, self.stop)
        threading.Thread(target=loop, daemon=True).start()

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
            return
        self.selected = rect
        self.overlay.show(rect)
        self.clear_btn.config(state="normal")
        x, y, w, h = rect
        self.status.set(f"Selected: {x},{y} {w}x{h}")

    def on_clear(self):
        self.selected = None
        self.overlay.hide()
        self.clear_btn.config(state="disabled")
        self.status.set("Selection cleared")

    def on_record(self):
        if not self.selected:
            self.status.set("Please select an area first")
            return
        name = self.fname.get().strip()
        if not name:
            self.status.set("Please enter filename")
            return
        if not shutil.which("ffmpeg"):
            self.status.set("ffmpeg not found in PATH")
            return

        base = os.path.join(DEFAULT_DIR, name)
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
        cmd = [
            "ffmpeg", "-y", *grab,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            self.out_mp4,
        ]

        self.record_btn.config(state="disabled")
        self.select_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status.set(f"Starting in {delay}s...")

        def worker():
            try:
                time.sleep(delay)
                self.set_status("Recording...")
                self.ffproc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
                self.ffproc.wait()
                self.ffproc = None
                self.root.after(0, self.on_finished, to_gif, fps)
            except Exception as e:
                print("Recording error:", e)
                self.ffproc = None
                self.set_status(f"Error: {e}")
                self.root.after(0, self._reset_buttons)

        threading.Thread(target=worker, daemon=True).start()

    def stop(self):
        p = self.ffproc
        if not p:
            self.status.set("Not recording")
            return
        try:
            p.stdin.write(b"q")  # ffmpeg finalizes the file on 'q'
            p.stdin.flush()
            self.status.set("Stopping...")
        except Exception as e:
            print("Stop error:", e)
            p.terminate()

    def _reset_buttons(self):
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
    App().run()


if __name__ == "__main__":
    main()

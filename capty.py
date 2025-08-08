#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GdkX11, GLib
import subprocess
import os
import signal
import time
from threading import Thread
import shutil

HOME = os.path.expanduser("~")
DEFAULT_DIR = os.path.join(HOME, "Videos")
os.makedirs(DEFAULT_DIR, exist_ok=True)

FRAMERATE = 15


class EdgeWindow(Gtk.Window):
    def __init__(self, parent_hide_callback, color_rgba=(1.0, 0.6, 0.0, 0.6)):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.parent_hide_callback = parent_hide_callback
        self.color_rgba = color_rgba
        self.hide_on_input = False

        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_app_paintable(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)

        screen = Gdk.Screen.get_default()
        try:
            if screen.is_composited():
                rgba_visual = screen.get_rgba_visual()
                if rgba_visual:
                    self.set_visual(rgba_visual)
        except Exception:
            pass

        self.connect("draw", self.on_draw)

    def set_geometry(self, x: int, y: int, w: int, h: int):
        self.move(int(x), int(y))
        self.resize(int(max(1, w)), int(max(1, h)))

    def on_draw(self, widget, cr):
        cr.set_source_rgba(*self.color_rgba)
        cr.rectangle(0, 0, widget.get_allocated_width(), widget.get_allocated_height())
        cr.fill()


class OverlayWindow:
    """Manages four thin border windows forming a click-through ring."""
    def __init__(self):
        self.border_thickness = 3
        self.rect = None
        self.top = EdgeWindow(self._hide_all)
        self.bottom = EdgeWindow(self._hide_all)
        self.left = EdgeWindow(self._hide_all)
        self.right = EdgeWindow(self._hide_all)
        self._hidden = True

    def _hide_all(self):
        self.top.hide()
        self.bottom.hide()
        self.left.hide()
        self.right.hide()
        self._hidden = True

    def show_all(self):
        if not self.rect:
            return
        self.top.show_all()
        self.bottom.show_all()
        self.left.show_all()
        self.right.show_all()
        self._hidden = False

    def hide(self):
        self._hide_all()

    def set_rect(self, rect):
        self.rect = rect
        if not rect:
            self._hide_all()
            return
        x, y, w, h = rect
        t = self.border_thickness
        # Draw borders just OUTSIDE the selection to guarantee the inner area is never covered
        # Top (outside)
        self.top.set_geometry(x - t, y - t, w + 2 * t, t)
        # Bottom (outside)
        self.bottom.set_geometry(x - t, y + h, w + 2 * t, t)
        # Left (outside)
        self.left.set_geometry(x - t, y, t, h)
        # Right (outside)
        self.right.set_geometry(x + w, y, t, h)
        if not self._hidden:
            self.show_all()

    def clear_rect(self):
        self.rect = None
        self._hide_all()


class RecorderUI:
    def __init__(self):
        # Main floating control window
        self.window = Gtk.Window(title="Selection")
        self.window.set_border_width(10)
        self.window.set_resizable(False)
        self.window.set_keep_above(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.window.set_default_size(320, 200)
        self.window.connect("destroy", Gtk.main_quit)

        # Layout
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.window.add(v)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        v.pack_start(hbox, False, False, 0)

        self.select_btn = Gtk.Button(label="Select area")
        self.select_btn.connect("clicked", self.on_select_area)
        hbox.pack_start(self.select_btn, True, True, 0)

        self.clear_btn = Gtk.Button(label="Clear")
        self.clear_btn.connect("clicked", self.on_clear_selection)
        self.clear_btn.set_sensitive(False)
        hbox.pack_start(self.clear_btn, True, True, 0)

        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        v.pack_start(grid, False, False, 0)

        grid.attach(Gtk.Label(label="Filename:"), 0, 0, 1, 1)
        self.filename_entry = Gtk.Entry()
        self.filename_entry.set_text(f"capture-{time.strftime("-%Y-%m-%d-%H-%M-%S")}")
        grid.attach(self.filename_entry, 1, 0, 2, 1)

        grid.attach(Gtk.Label(label="Delay (s):"), 0, 1, 1, 1)
        # Use keyword args for Adjustment (avoid deprecation warning)
        self.delay_spin = Gtk.SpinButton()
        adj = Gtk.Adjustment(value=3, lower=0, upper=60, step_increment=1, page_increment=5, page_size=0)
        self.delay_spin.set_adjustment(adj)
        grid.attach(self.delay_spin, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Format:"), 0, 2, 1, 1)
        fmt_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.format_mp4 = Gtk.RadioButton.new_with_label(None, "MP4 (video)")
        self.format_gif = Gtk.RadioButton.new_with_label_from_widget(self.format_mp4, "GIF (animated)")
        fmt_box.pack_start(self.format_mp4, False, False, 0)
        fmt_box.pack_start(self.format_gif, False, False, 0)
        grid.attach(fmt_box, 1, 2, 2, 1)

        # Framerate input
        grid.attach(Gtk.Label(label="FPS:"), 0, 3, 1, 1)
        self.fps_spin = Gtk.SpinButton()
        fps_adj = Gtk.Adjustment(value=30, lower=1, upper=240, step_increment=1, page_increment=10, page_size=0)
        self.fps_spin.set_adjustment(fps_adj)
        grid.attach(self.fps_spin, 1, 3, 1, 1)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        v.pack_start(btn_box, False, False, 0)
        self.record_btn = Gtk.Button(label="Record")
        self.record_btn.get_style_context().add_class("suggested-action")
        self.record_btn.connect("clicked", self.on_record_clicked)
        btn_box.pack_start(self.record_btn, True, True, 0)

        self.stop_btn = Gtk.Button(label="Stop")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self.on_stop_clicked)
        btn_box.pack_start(self.stop_btn, True, True, 0)

        self.status = Gtk.Label(label="Ready")
        v.pack_start(self.status, False, False, 0)

        self.window.connect("key-press-event", self.on_key_press)

        # Overlay that shows the selected rectangle (only visible while selecting / idle)
        self.overlay = OverlayWindow()

        # State
        self.selected = None  # (x, y, w, h)
        self.ffproc = None
        self.record_thread = None
        self.out_mp4 = None
        self.out_gif = None
        self.palette = None

    def show(self):
        self.window.show_all()

    def on_select_area(self, btn):
        """Use slop to let user draw selection; show overlay with border."""
        try:
            res = subprocess.run(["slop", "-f", "%x %y %w %h"], check=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            txt = res.stdout.strip()
            if not txt:
                self.status.set_text("Selection cancelled")
                return
            x, y, w, h = map(int, txt.split())
            self.selected = (x, y, w, h)
            self.overlay.set_rect(self.selected)
            self.overlay.show_all()
            self.clear_btn.set_sensitive(True)
            self.status.set_text(f"Selected: {x},{y} {w}x{h}")
        except subprocess.CalledProcessError as e:
            self.status.set_text("Selection cancelled or slop error")
            print("slop error:", e)

    def on_clear_selection(self, btn):
        self.selected = None
        self.overlay.clear_rect()
        self.overlay.hide()
        self.clear_btn.set_sensitive(False)
        self.status.set_text("Selection cleared")

    def on_record_clicked(self, btn):
        if not self.selected:
            self.status.set_text("Please select an area first")
            return

        fname = self.filename_entry.get_text().strip()
        if not fname:
            self.status.set_text("Please enter filename")
            return

        delay = int(self.delay_spin.get_value_as_int())
        to_gif = self.format_gif.get_active()

        outdir = DEFAULT_DIR
        os.makedirs(outdir, exist_ok=True)
        base_path = os.path.join(outdir, fname)
        # Prevent overwrite: if any target for this base exists, append timestamp suffix
        mp4_candidate = f"{base_path}.mp4"
        gif_candidate = f"{base_path}.gif"
        palette_candidate = f"{base_path}_palette.png"
        if os.path.exists(mp4_candidate) or os.path.exists(gif_candidate) or os.path.exists(palette_candidate):
            suffix = time.strftime("-%Y-%m-%d-%H-%M-%S")
            base_path = f"{base_path}{suffix}"
        mp4_path = f"{base_path}.mp4"
        gif_path = f"{base_path}.gif"
        palette = f"{base_path}_palette.png"

        self.out_mp4 = mp4_path
        self.out_gif = gif_path
        self.palette = palette

        x, y, w, h = self.selected

        fps = int(self.fps_spin.get_value_as_int()) if hasattr(self, 'fps_spin') else FRAMERATE
        ff_cmd = [
            "ffmpeg", "-y",
            "-f", "x11grab",
            "-video_size", f"{w}x{h}",
            "-framerate", str(fps),
            "-i", f":0.0+{x},{y}",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "18",
            mp4_path
        ]

        # Update UI before starting
        self.record_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(True)
        self.select_btn.set_sensitive(False)
        self.status.set_text(f"Starting in {delay}s...")

        def record_worker():
            try:
                # short delay
                time.sleep(delay)
                GLib.idle_add(self.status.set_text, "Recording...")
                # Start ffmpeg as a process group so we can stop it gracefully
                self.ffproc = subprocess.Popen(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                self.ffproc.wait()
                GLib.idle_add(self.on_record_finished, to_gif)
            except Exception as e:
                print("Recording error:", e)
                GLib.idle_add(self.status.set_text, f"Error: {e}")
                self.ffproc = None

        self.record_thread = Thread(target=record_worker, daemon=True)
        self.record_thread.start()

    def on_stop_clicked(self, btn):
        self._stop_recording()

    def on_key_press(self, widget, event):
        # Ctrl+Alt+S -> stop
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        alt = event.state & Gdk.ModifierType.MOD1_MASK
        keyval = Gdk.keyval_name(event.keyval)
        if ctrl and alt and keyval and keyval.lower() == "s":
            if self.ffproc:
                self._stop_recording()
            return True
        return False

    def _stop_recording(self):
        if not self.ffproc:
            self.status.set_text("Not recording")
            return
        try:
            os.killpg(os.getpgid(self.ffproc.pid), signal.SIGINT)
            self.status.set_text("Stopping...")
        except Exception as e:
            print("Stop error:", e)
            try:
                self.ffproc.terminate()
            except:
                pass

    def on_record_finished(self, to_gif):
        self.status.set_text("Recording finished")
        self.record_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self.select_btn.set_sensitive(True)

        if to_gif:
            self.status.set_text("Converting to GIF...")
            try:
                fps = int(self.fps_spin.get_value_as_int()) if hasattr(self, 'fps_spin') else FRAMERATE
                pg_cmd = [
                    "ffmpeg", "-y", "-i", self.out_mp4,
                    "-vf", f"fps={fps},scale=iw:-1:flags=lanczos,palettegen",
                    self.palette
                ]
                subprocess.run(pg_cmd, check=True)
                pu_cmd = [
                    "ffmpeg", "-y", "-i", self.out_mp4, "-i", self.palette,
                    "-filter_complex", f"fps={fps},scale=iw:-1:flags=lanczos[x];[x][1:v]paletteuse",
                    self.out_gif
                ]
                subprocess.run(pu_cmd, check=True)
                if shutil.which("gifsicle"):
                    subprocess.run(["gifsicle", "-O3", self.out_gif, "-o", self.out_gif], check=True)
                self.status.set_text(f"Saved GIF: {self.out_gif}")
            except Exception as e:
                print("GIF conversion error:", e)
                self.status.set_text("GIF conversion failed")
        else:
            self.status.set_text(f"Saved MP4: {self.out_mp4}")


def main():
    app = RecorderUI()
    app.show()
    Gtk.main()


if __name__ == "__main__":
    main()

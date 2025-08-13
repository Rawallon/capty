#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GdkX11, GLib
import subprocess
import os
import signal
import time
import logging
from threading import Thread
import shutil
import json

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('capty.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

HOME = os.path.expanduser("~")
DEFAULT_DIR = os.path.join(HOME, "Videos")
os.makedirs(DEFAULT_DIR, exist_ok=True)

FRAMERATE = 15

# CSS for modern styling
CSS_STYLE = """
.window {
    background: linear-gradient(180deg, #FF8C00 0%, #DC143C 100%);
    border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.control-bar {
    background: rgba(139, 69, 19, 0.9);
    border-radius: 8px;
    padding: 8px;
    margin: 8px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
}

.option-button {
    background: rgba(160, 82, 45, 0.8);
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    color: white;
    font-weight: bold;
    transition: all 0.2s ease;
}

.option-button:hover {
    background: rgba(160, 82, 45, 1.0);
}

.option-button:active {
    background: rgba(139, 69, 19, 1.0);
}

.audio-toggle {
    background: rgba(160, 82, 45, 0.8);
    border: none;
    border-radius: 8px;
    padding: 10px 15px;
    color: white;
    font-weight: bold;
    margin: 0 5px;
    transition: all 0.2s ease;
}

.audio-toggle:hover {
    background: rgba(160, 82, 45, 1.0);
}

.audio-toggle.active {
    background: rgba(34, 139, 34, 0.9);
}

.audio-toggle.inactive {
    background: rgba(139, 69, 19, 0.9);
}

.dropdown-button {
    background: rgba(160, 82, 45, 0.8);
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    color: white;
    font-weight: bold;
    transition: all 0.2s ease;
}

.dropdown-button:hover {
    background: rgba(160, 82, 45, 1.0);
}

.dropdown-menu {
    background: rgba(139, 69, 19, 0.95);
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.2);
}

.dropdown-item {
    background: transparent;
    border: none;
    color: white;
    padding: 8px 12px;
    transition: background 0.2s ease;
}

.dropdown-item:hover {
    background: rgba(160, 82, 45, 0.8);
}

.record-button {
    background: rgba(220, 20, 60, 0.9);
    border: none;
    border-radius: 8px;
    padding: 12px 20px;
    color: white;
    font-weight: bold;
    font-size: 14px;
    transition: all 0.2s ease;
}

.record-button:hover {
    background: rgba(220, 20, 60, 1.0);
}

.record-button:active {
    background: rgba(178, 34, 34, 1.0);
}

.stop-button {
    background: rgba(128, 128, 128, 0.9);
    border: none;
    border-radius: 8px;
    padding: 12px 20px;
    color: white;
    font-weight: bold;
    font-size: 14px;
    transition: all 0.2s ease;
}

.stop-button:hover {
    background: rgba(128, 128, 128, 1.0);
}

.close-button {
    background: rgba(160, 82, 45, 0.8);
    border: none;
    border-radius: 4px;
    padding: 6px 10px;
    color: white;
    font-weight: bold;
    transition: all 0.2s ease;
}

.close-button:hover {
    background: rgba(220, 20, 60, 0.9);
}

.status-label {
    color: white;
    font-weight: bold;
    background: rgba(0, 0, 0, 0.3);
    border-radius: 4px;
    padding: 4px 8px;
}
"""


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
        self.window = Gtk.Window(title="Capty Screen Recorder")
        self.window.set_border_width(0)
        self.window.set_resizable(False)
        self.window.set_keep_above(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.window.set_default_size(400, 300)
        self.window.connect("destroy", Gtk.main_quit)
        
        # Apply CSS styling
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLE.encode())
        screen = Gdk.Screen.get_default()
        style_context = Gtk.StyleContext()
        style_context.add_provider_for_screen(screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        # Add CSS class to window
        self.window.get_style_context().add_class("window")

        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.add(main_box)

        # Control bar (the brown bar from the image)
        control_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        control_bar.get_style_context().add_class("control-bar")
        main_box.pack_start(control_bar, False, False, 0)

        # Close button
        close_btn = Gtk.Button(label="✕")
        close_btn.get_style_context().add_class("close-button")
        close_btn.connect("clicked", lambda w: Gtk.main_quit())
        control_bar.pack_start(close_btn, False, False, 0)

        # Top options: Display, Window, Area
        options_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        control_bar.pack_start(options_box, True, True, 0)

        # Display button with dropdown
        self.display_btn = Gtk.Button(label="Display")
        self.display_btn.get_style_context().add_class("option-button")
        self.display_btn.connect("clicked", self.on_display_clicked)
        options_box.pack_start(self.display_btn, False, False, 0)

        # Area button
        self.area_btn = Gtk.Button(label="Area")
        self.area_btn.get_style_context().add_class("option-button")
        self.area_btn.connect("clicked", self.on_area_clicked)
        options_box.pack_start(self.area_btn, False, False, 0)

        # Audio toggles
        audio_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        control_bar.pack_start(audio_box, False, False, 0)

        # Microphone toggle
        self.mic_btn = Gtk.Button(label="🎤 No microphone")
        self.mic_btn.get_style_context().add_class("audio-toggle")
        self.mic_btn.get_style_context().add_class("inactive")
        self.mic_btn.connect("clicked", self.on_mic_toggle)
        self.mic_enabled = False
        audio_box.pack_start(self.mic_btn, False, False, 0)

        # System audio toggle
        self.system_audio_btn = Gtk.Button(label="🔊 No system audio")
        self.system_audio_btn.get_style_context().add_class("audio-toggle")
        self.system_audio_btn.get_style_context().add_class("inactive")
        self.system_audio_btn.connect("clicked", self.on_system_audio_toggle)
        self.system_audio_enabled = False
        audio_box.pack_start(self.system_audio_btn, False, False, 0)

        # Settings and dropdown arrow
        settings_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        control_bar.pack_end(settings_box, False, False, 0)

        settings_btn = Gtk.Button(label="⚙")
        settings_btn.get_style_context().add_class("option-button")
        settings_btn.connect("clicked", self.on_settings_clicked)
        settings_box.pack_start(settings_btn, False, False, 0)

        dropdown_btn = Gtk.Button(label="▼")
        dropdown_btn.get_style_context().add_class("dropdown-button")
        dropdown_btn.connect("clicked", self.on_dropdown_clicked)
        settings_box.pack_start(dropdown_btn, False, False, 0)

        # Main content area
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)
        content_box.set_margin_top(20)
        content_box.set_margin_bottom(20)
        main_box.pack_start(content_box, True, True, 0)

        # Filename input
        filename_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content_box.pack_start(filename_box, False, False, 0)
        
        filename_label = Gtk.Label(label="Filename:")
        filename_label.get_style_context().add_class("status-label")
        filename_box.pack_start(filename_label, False, False, 0)
        
        self.filename_entry = Gtk.Entry()
        self.filename_entry.set_text(f"capture-{time.strftime('%Y-%m-%d-%H-%M-%S')}")
        filename_box.pack_start(self.filename_entry, True, True, 0)

        # Format selection
        format_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content_box.pack_start(format_box, False, False, 0)
        
        format_label = Gtk.Label(label="Format:")
        format_label.get_style_context().add_class("status-label")
        format_box.pack_start(format_label, False, False, 0)
        
        self.format_mp4 = Gtk.RadioButton.new_with_label(None, "MP4")
        self.format_gif = Gtk.RadioButton.new_with_label_from_widget(self.format_mp4, "GIF")
        format_box.pack_start(self.format_mp4, False, False, 0)
        format_box.pack_start(self.format_gif, False, False, 0)

        # FPS input
        fps_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content_box.pack_start(fps_box, False, False, 0)
        
        fps_label = Gtk.Label(label="FPS:")
        fps_label.get_style_context().add_class("status-label")
        fps_box.pack_start(fps_label, False, False, 0)
        
        self.fps_spin = Gtk.SpinButton()
        fps_adj = Gtk.Adjustment(value=30, lower=1, upper=240, step_increment=1, page_increment=10, page_size=0)
        self.fps_spin.set_adjustment(fps_adj)
        fps_box.pack_start(self.fps_spin, False, False, 0)

        # Record/Stop buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        content_box.pack_start(button_box, False, False, 0)
        
        self.record_btn = Gtk.Button(label="Record")
        self.record_btn.get_style_context().add_class("record-button")
        self.record_btn.connect("clicked", self.on_record_clicked)
        button_box.pack_start(self.record_btn, True, True, 0)

        self.stop_btn = Gtk.Button(label="Stop")
        self.stop_btn.get_style_context().add_class("stop-button")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self.on_stop_clicked)
        button_box.pack_start(self.stop_btn, True, True, 0)

        # Status label
        self.status = Gtk.Label(label="Ready to record")
        self.status.get_style_context().add_class("status-label")
        content_box.pack_start(self.status, False, False, 0)

        # Display dropdown popover
        self.display_popover = Gtk.Popover()
        self.display_popover.get_style_context().add_class("dropdown-menu")
        self.display_popover.set_relative_to(self.display_btn)
        self.display_popover.set_position(Gtk.PositionType.BOTTOM)
        
        self.display_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.display_popover.add(self.display_list)
        
        # Get available displays
        self.displays = self.get_available_displays()
        self.selected_display = None
        self.populate_display_list()

        # Overlay that shows the selected rectangle
        self.overlay = OverlayWindow()

        # State
        self.selected = None  # (x, y, w, h)
        self.ffproc = None
        self.record_thread = None
        self.out_mp4 = None
        self.out_gif = None
        self.palette = None
        self.recording_mode = None  # 'display', 'window', 'area'

        # Log initialization
        logger.info("Capty Screen Recorder initialized")

    def get_available_displays(self):
        """Get list of available displays"""
        try:
            # Use xrandr to get display information
            result = subprocess.run(["xrandr", "--listmonitors"], 
                                  capture_output=True, text=True, check=True)
            displays = []
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            for line in lines:
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        display_name = parts[0]
                        resolution = f"{parts[2]}x{parts[3]}"
                        displays.append({
                            'name': display_name,
                            'resolution': resolution,
                            'full_name': f"{display_name} ({resolution})"
                        })
            logger.info(f"Found {len(displays)} displays: {displays}")
            return displays
        except Exception as e:
            logger.error(f"Error getting displays: {e}")
            return [{'name': 'default', 'resolution': '1920x1080', 'full_name': 'Default Display'}]

    def populate_display_list(self):
        """Populate the display dropdown list"""
        for child in self.display_list.get_children():
            self.display_list.remove(child)
        
        for display in self.displays:
            btn = Gtk.Button(label=display['full_name'])
            btn.get_style_context().add_class("dropdown-item")
            btn.connect("clicked", self.on_display_selected, display)
            self.display_list.pack_start(btn, False, False, 0)
        
        self.display_list.show_all()

    def on_display_clicked(self, button):
        """Handle display button click"""
        logger.info("Display button clicked")
        self.display_popover.show_all()
        self.recording_mode = 'display'

    def on_display_selected(self, button, display):
        """Handle display selection from dropdown"""
        self.selected_display = display
        self.display_btn.set_label(f"Display: {display['name']}")
        self.display_popover.hide()
        logger.info(f"Display selected: {display['name']} ({display['resolution']})")
        self.status.set_text(f"Selected display: {display['name']}")

    def on_area_clicked(self, button):
        """Handle area selection"""
        logger.info("Area button clicked")
        self.recording_mode = 'area'
        self.select_area()

    def on_mic_toggle(self, button):
        """Toggle microphone recording"""
        self.mic_enabled = not self.mic_enabled
        if self.mic_enabled:
            button.set_label("🎤 Microphone")
            button.get_style_context().remove_class("inactive")
            button.get_style_context().add_class("active")
            logger.info("Microphone enabled")
        else:
            button.set_label("🎤 No microphone")
            button.get_style_context().remove_class("active")
            button.get_style_context().add_class("inactive")
            logger.info("Microphone disabled")

    def on_system_audio_toggle(self, button):
        """Toggle system audio recording"""
        self.system_audio_enabled = not self.system_audio_enabled
        if self.system_audio_enabled:
            button.set_label("🔊 System audio")
            button.get_style_context().remove_class("inactive")
            button.get_style_context().add_class("active")
            logger.info("System audio enabled")
        else:
            button.set_label("🔊 No system audio")
            button.get_style_context().remove_class("active")
            button.get_style_context().add_class("inactive")
            logger.info("System audio disabled")

    def on_settings_clicked(self, button):
        """Handle settings button click"""
        logger.info("Settings button clicked")
        # TODO: Implement settings dialog
        self.status.set_text("Settings (not implemented yet)")

    def on_dropdown_clicked(self, button):
        """Handle dropdown arrow click"""
        logger.info("Dropdown arrow clicked")
        # TODO: Implement additional options menu
        self.status.set_text("More options (not implemented yet)")

    def select_area(self):
        """Select an area for recording"""
        try:
            logger.info("Starting area selection")
            self.status.set_text("Select an area...")
            
            # Use slop to select area
            res = subprocess.run(["slop", "-f", "%x %y %w %h"], 
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            txt = res.stdout.strip()
            if not txt:
                logger.info("Area selection cancelled")
                self.status.set_text("Area selection cancelled")
                return
                
            x, y, w, h = map(int, txt.split())
            self.selected = (x, y, w, h)
            self.overlay.set_rect(self.selected)
            self.overlay.show_all()
            
            logger.info(f"Area selected: {x},{y} {w}x{h}")
            self.status.set_text(f"Area selected: {w}x{h}")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Area selection error: {e}")
            self.status.set_text("Area selection failed")

    def show(self):
        self.window.show_all()

    def on_record_clicked(self, btn):
        """Handle record button click"""
        logger.info("Record button clicked")
        
        # Determine what to record based on mode
        if self.recording_mode == 'display':
            if not self.selected_display:
                self.status.set_text("Please select a display first")
                logger.warning("No display selected")
                return
            # For display recording, we'll use the full display area
            # This is a simplified implementation - you might want to get actual display geometry
            self.selected = (0, 0, 1920, 1080)  # Default, should be improved
            logger.info(f"Recording display: {self.selected_display['name']}")
        elif self.recording_mode == 'window' or self.recording_mode == 'area':
            if not self.selected:
                self.status.set_text("Please select a window/area first")
                logger.warning("No window/area selected")
                return
        else:
            self.status.set_text("Please select recording mode (Display/Window/Area)")
            logger.warning("No recording mode selected")
            return

        fname = self.filename_entry.get_text().strip()
        if not fname:
            self.status.set_text("Please enter filename")
            logger.warning("No filename entered")
            return

        # Prepare output paths
        outdir = DEFAULT_DIR
        os.makedirs(outdir, exist_ok=True)
        base_path = os.path.join(outdir, fname)
        
        # Prevent overwrite
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
        fps = int(self.fps_spin.get_value_as_int())

        # Build ffmpeg command
        ff_cmd = [
            "ffmpeg", "-y",
            "-f", "x11grab",
            "-video_size", f"{w}x{h}",
            "-framerate", str(fps),
            "-i", f":0.0+{x},{y}"
        ]

        # Add audio inputs if enabled
        if self.mic_enabled:
            ff_cmd.extend(["-f", "pulse", "-i", "default"])
            logger.info("Microphone input added to recording")
            
        if self.system_audio_enabled:
            # For system audio, we need to capture from pulseaudio
            # This is a simplified approach - might need adjustment for your system
            ff_cmd.extend(["-f", "pulse", "-i", "default.monitor"])
            logger.info("System audio input added to recording")

        # Add video codec
        ff_cmd.extend([
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "18"
        ])

        # Add audio codec if any audio is enabled
        if self.mic_enabled or self.system_audio_enabled:
            ff_cmd.extend(["-c:a", "aac", "-b:a", "128k"])

        ff_cmd.append(mp4_path)

        logger.info(f"FFmpeg command: {' '.join(ff_cmd)}")

        # Update UI
        self.record_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(True)
        self.status.set_text("Starting recording...")

        def record_worker():
            try:
                logger.info("Starting recording process")
                self.ffproc = subprocess.Popen(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                logger.info(f"FFmpeg process started with PID: {self.ffproc.pid}")
                GLib.idle_add(self.status.set_text, "Recording...")
                self.ffproc.wait()
                logger.info("FFmpeg process finished")
                GLib.idle_add(self.on_record_finished, self.format_gif.get_active())
            except Exception as e:
                logger.error(f"Recording error: {e}")
                GLib.idle_add(self.status.set_text, f"Error: {e}")
                self.ffproc = None

        self.record_thread = Thread(target=record_worker, daemon=True)
        self.record_thread.start()

    def on_stop_clicked(self, btn):
        """Handle stop button click"""
        logger.info("Stop button clicked")
        self._stop_recording()

    def _stop_recording(self):
        """Stop the recording process"""
        if not self.ffproc:
            logger.warning("No recording process to stop")
            self.status.set_text("Not recording")
            return
        try:
            logger.info(f"Stopping recording process (PID: {self.ffproc.pid})")
            os.killpg(os.getpgid(self.ffproc.pid), signal.SIGINT)
            self.status.set_text("Stopping...")
        except Exception as e:
            logger.error(f"Stop error: {e}")
            try:
                self.ffproc.terminate()
                logger.info("Process terminated")
            except:
                logger.error("Failed to terminate process")

    def on_record_finished(self, to_gif):
        """Handle recording completion"""
        logger.info("Recording finished")
        self.status.set_text("Recording finished")
        self.record_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)

        if to_gif:
            logger.info("Starting GIF conversion")
            self.status.set_text("Converting to GIF...")
            try:
                fps = int(self.fps_spin.get_value_as_int())
                
                # Generate palette
                logger.info("Generating palette")
                pg_cmd = [
                    "ffmpeg", "-y", "-i", self.out_mp4,
                    "-vf", f"fps={fps},scale=iw:-1:flags=lanczos,palettegen",
                    self.palette
                ]
                subprocess.run(pg_cmd, check=True)
                logger.info("Palette generated")
                
                # Create GIF
                logger.info("Creating GIF")
                pu_cmd = [
                    "ffmpeg", "-y", "-i", self.out_mp4, "-i", self.palette,
                    "-filter_complex", f"fps={fps},scale=iw:-1:flags=lanczos[x];[x][1:v]paletteuse",
                    self.out_gif
                ]
                subprocess.run(pu_cmd, check=True)
                logger.info("GIF created")
                
                # Optimize if gifsicle is available
                if shutil.which("gifsicle"):
                    logger.info("Optimizing GIF with gifsicle")
                    subprocess.run(["gifsicle", "-O3", self.out_gif, "-o", self.out_gif], check=True)
                    logger.info("GIF optimized")
                    
                self.status.set_text(f"Saved GIF: {self.out_gif}")
                logger.info(f"GIF saved: {self.out_gif}")
            except Exception as e:
                logger.error(f"GIF conversion error: {e}")
                self.status.set_text("GIF conversion failed")
        else:
            self.status.set_text(f"Saved MP4: {self.out_mp4}")
            logger.info(f"MP4 saved: {self.out_mp4}")


def main():
    logger.info("Starting Capty Screen Recorder")
    app = RecorderUI()
    app.show()
    Gtk.main()


if __name__ == "__main__":
    main()

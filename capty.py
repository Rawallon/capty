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
/* Floating bar styling */
window {
    background: rgba(40, 40, 40, 0.85);
    border-radius: 12px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.floating-bar {
    background: rgba(60, 60, 60, 0.9);
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.1);
}

/* Button styling */
.scope-button {
    background: rgba(80, 80, 80, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 6px;
    color: white;
    font-weight: bold;
    transition: all 0.2s ease;
}

.scope-button:hover {
    background: rgba(100, 100, 100, 0.9);
    border-color: rgba(255, 255, 255, 0.4);
}

.scope-button.selected {
    background: rgba(100, 150, 255, 0.8);
    border-color: rgba(100, 150, 255, 1.0);
}

.status-button {
    background: rgba(80, 80, 80, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 6px;
    color: white;
    font-size: 12px;
    transition: all 0.2s ease;
}

.status-button:hover {
    background: rgba(100, 100, 100, 0.9);
}

.status-button.active {
    background: rgba(76, 175, 80, 0.8);
    border-color: rgba(76, 175, 80, 1.0);
}

.status-button.inactive {
    background: rgba(244, 67, 54, 0.8);
    border-color: rgba(244, 67, 54, 1.0);
}

.settings-button {
    background: rgba(80, 80, 80, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 6px;
    color: white;
    font-weight: bold;
    transition: all 0.2s ease;
}

.settings-button:hover {
    background: rgba(100, 100, 100, 0.9);
}

.close-button {
    background: rgba(244, 67, 54, 0.8);
    border: none;
    border-radius: 4px;
    color: white;
    font-weight: bold;
    transition: all 0.2s ease;
}

.close-button:hover {
    background: rgba(244, 67, 54, 1.0);
}

/* Separator styling */
separator {
    background-color: rgba(100, 100, 100, 0.5);
}

/* Settings popup styling */
.settings-popup {
    background: rgba(50, 50, 50, 0.95);
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.settings-title {
    color: white;
    font-size: 16px;
    font-weight: bold;
}

/* Form elements in settings */
entry {
    background: rgba(60, 60, 60, 0.8);
    border: 1px solid rgba(100, 100, 100, 0.5);
    border-radius: 4px;
    padding: 6px;
    color: white;
}

entry:focus {
    border-color: rgba(100, 150, 255, 0.8);
}

spinbutton {
    background: rgba(60, 60, 60, 0.8);
    border: 1px solid rgba(100, 100, 100, 0.5);
    border-radius: 4px;
    color: white;
}

radiobutton {
    color: white;
}

label {
    color: white;
}

/* Record/Stop buttons */
.record-button {
    background: rgba(76, 175, 80, 0.9);
    border: 1px solid rgba(76, 175, 80, 0.3);
    border-radius: 6px;
    color: white;
    font-weight: bold;
    font-size: 12px;
    transition: all 0.2s ease;
}

.record-button:hover {
    background: rgba(76, 175, 80, 1.0);
    border-color: rgba(76, 175, 80, 0.8);
}

.stop-button {
    background: rgba(128, 128, 128, 0.9);
    border: 1px solid rgba(128, 128, 128, 0.3);
    border-radius: 6px;
    color: white;
    font-weight: bold;
    font-size: 12px;
    transition: all 0.2s ease;
}

.stop-button:hover {
    background: rgba(128, 128, 128, 1.0);
    border-color: rgba(128, 128, 128, 0.8);
}

.disabled-button {
    background: rgba(128, 128, 128, 0.5);
    border: 1px solid rgba(128, 128, 128, 0.3);
    border-radius: 6px;
    color: rgba(255, 255, 255, 0.5);
    font-weight: bold;
    font-size: 12px;
    transition: all 0.2s ease;
}

.disabled-button:hover {
    background: rgba(128, 128, 128, 0.5);
    border-color: rgba(128, 128, 128, 0.3);
}

.close-settings-button {
    background: rgba(80, 80, 80, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 6px;
    padding: 8px 16px;
    color: white;
    transition: all 0.2s ease;
}

.close-settings-button:hover {
    background: rgba(100, 100, 100, 0.9);
}

.status-label {
    color: white;
    font-weight: bold;
    background: rgba(0, 0, 0, 0.3);
    border-radius: 4px;
    padding: 4px 8px;
}

/* Dropdown styling */
.dropdown-menu {
    background: rgba(50, 50, 50, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 8px;
    color: white;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
}

.dropdown-item {
    background: rgba(60, 60, 60, 0.8);
    border: none;
    border-radius: 4px;
    padding: 8px 12px;
    color: white;
    font-weight: bold;
    transition: all 0.2s ease;
    margin: 2px;
}

.dropdown-item:hover {
    background: rgba(100, 150, 255, 0.8);
    color: white;
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
        # Main floating control bar
        self.window = Gtk.Window(title="Capty")
        self.window.set_decorated(False)  # No window decorations
        self.window.set_keep_above(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.window.set_default_size(500, 50)

        self.window.connect("destroy", Gtk.main_quit)
        
        # Make window draggable
        self.window.connect("button-press-event", self.on_window_button_press)
        self.window.connect("button-release-event", self.on_window_button_release)
        self.window.connect("motion-notify-event", self.on_window_motion)
        self.window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        
        # Position window at bottom center of screen
        self.center_window_bottom()
        
        # Apply CSS styling
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLE.encode())
        screen = Gdk.Screen.get_default()
        style_context = Gtk.StyleContext()
        style_context.add_provider_for_screen(screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Main horizontal control bar
        control_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        control_bar.set_margin_start(12)
        control_bar.set_margin_end(12)
        control_bar.set_margin_top(8)
        control_bar.set_margin_bottom(8)
        control_bar.get_style_context().add_class("floating-bar")
        self.window.add(control_bar)

        # Close button (X)
        close_btn = Gtk.Button(label="✕")
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        close_btn.set_size_request(24, 24)
        close_btn.connect("clicked", lambda w: Gtk.main_quit())
        close_btn.get_style_context().add_class("close-button")
        control_bar.pack_start(close_btn, False, False, 0)

        # Recording scope options
        scope_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        control_bar.pack_start(scope_box, False, False, 0)
        
        # Display button
        self.display_btn = Gtk.Button(label="Display")
        self.display_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.display_btn.set_size_request(60, 30)
        self.display_btn.get_style_context().add_class("scope-button")
        self.display_btn.connect("clicked", self.on_display_clicked)
        scope_box.pack_start(self.display_btn, False, False, 0)

        # Area button
        self.area_btn = Gtk.Button(label="Area")
        self.area_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.area_btn.set_size_request(60, 30)
        self.area_btn.get_style_context().add_class("scope-button")
        self.area_btn.get_style_context().add_class("selected")
        self.area_btn.connect("clicked", self.on_area_clicked)
        scope_box.pack_start(self.area_btn, False, False, 0)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        control_bar.pack_start(separator, False, False, 0)

        # Audio status indicators
        audio_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        control_bar.pack_start(audio_box, False, False, 0)
        
        # Microphone status
        self.mic_btn = Gtk.Button(label="🎤 OFF")
        self.mic_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.mic_btn.set_size_request(70, 30)
        self.mic_btn.get_style_context().add_class("status-button")
        self.mic_btn.get_style_context().add_class("inactive")
        self.mic_btn.connect("clicked", self.on_mic_toggle)
        self.mic_enabled = False
        audio_box.pack_start(self.mic_btn, False, False, 0)

        # System audio status
        self.system_audio_btn = Gtk.Button(label="🔊 OFF")
        self.system_audio_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.system_audio_btn.set_size_request(80, 30)
        self.system_audio_btn.get_style_context().add_class("status-button")
        self.system_audio_btn.get_style_context().add_class("inactive")
        self.system_audio_btn.connect("clicked", self.on_system_audio_toggle)
        self.system_audio_enabled = False
        audio_box.pack_start(self.system_audio_btn, False, False, 0)

        # Separator
        separator2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        control_bar.pack_start(separator2, False, False, 0)

        # Record/Stop button (single toggle button)
        self.record_btn = Gtk.Button(label="🔴 Record")
        self.record_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.record_btn.set_size_request(80, 30)
        self.record_btn.get_style_context().add_class("record-button")
        self.record_btn.connect("clicked", self.on_record_clicked)
        control_bar.pack_start(self.record_btn, False, False, 0)

        # Separator
        separator3 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        control_bar.pack_start(separator3, False, False, 0)

        # Settings button
        settings_btn = Gtk.Button(label="⚙")
        settings_btn.set_relief(Gtk.ReliefStyle.NONE)
        settings_btn.set_size_request(32, 32)
        settings_btn.get_style_context().add_class("settings-button")
        settings_btn.connect("clicked", self.on_settings_clicked)
        control_bar.pack_start(settings_btn, False, False, 0)

        # Settings popup (initially hidden)
        self.settings_popup = Gtk.Window(title="Settings")
        self.settings_popup.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.settings_popup.set_default_size(350, 250)
        self.settings_popup.set_transient_for(self.window)
        self.settings_popup.set_modal(True)
        self.settings_popup.set_decorated(False)
        self.settings_popup.get_style_context().add_class("settings-popup")
        
        settings_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        settings_vbox.set_margin_start(20)
        settings_vbox.set_margin_end(20)
        settings_vbox.set_margin_top(20)
        settings_vbox.set_margin_bottom(20)
        self.settings_popup.add(settings_vbox)
        
        # Settings title
        title_label = Gtk.Label(label="<b>Recording Settings</b>", use_markup=True)
        title_label.get_style_context().add_class("settings-title")
        settings_vbox.pack_start(title_label, False, False, 0)
        
        # Filename
        filename_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        filename_box.pack_start(Gtk.Label(label="Filename:"), False, False, 0)
        self.filename_entry = Gtk.Entry()
        self.filename_entry.set_text(f"capty")
        filename_box.pack_start(self.filename_entry, True, True, 0)
        settings_vbox.pack_start(filename_box, False, False, 0)
        
        # Format
        format_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        format_box.pack_start(Gtk.Label(label="Format:"), False, False, 0)
        self.format_mp4 = Gtk.RadioButton.new_with_label(None, "MP4")
        self.format_gif = Gtk.RadioButton.new_with_label_from_widget(self.format_mp4, "GIF")
        format_box.pack_start(self.format_mp4, False, False, 0)
        format_box.pack_start(self.format_gif, False, False, 0)
        settings_vbox.pack_start(format_box, False, False, 0)
        
        # FPS
        fps_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        fps_box.pack_start(Gtk.Label(label="FPS:"), False, False, 0)
        self.fps_spin = Gtk.SpinButton()
        fps_adj = Gtk.Adjustment(value=30, lower=1, upper=240, step_increment=1, page_increment=10, page_size=0)
        self.fps_spin.set_adjustment(fps_adj)
        fps_box.pack_start(self.fps_spin, False, False, 0)
        settings_vbox.pack_start(fps_box, False, False, 0)
        
        # Delay
        delay_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        delay_box.pack_start(Gtk.Label(label="Delay (s):"), False, False, 0)
        self.delay_spin = Gtk.SpinButton()
        delay_adj = Gtk.Adjustment(value=3, lower=0, upper=60, step_increment=1, page_increment=5, page_size=0)
        self.delay_spin.set_adjustment(delay_adj)
        delay_box.pack_start(self.delay_spin, False, False, 0)
        settings_vbox.pack_start(delay_box, False, False, 0)
        

        
        # Status
        self.status = Gtk.Label(label="Ready")
        self.status.get_style_context().add_class("status-label")
        settings_vbox.pack_start(self.status, False, False, 0)
        
        # Close settings button
        close_settings_btn = Gtk.Button(label="Close")
        close_settings_btn.get_style_context().add_class("close-settings-button")
        close_settings_btn.connect("clicked", lambda w: self.settings_popup.hide())
        settings_vbox.pack_start(close_settings_btn, False, False, 0)

        # Display dropdown window (separate floating window)
        self.display_popup = Gtk.Window(title="Select Display")
        self.display_popup.set_type_hint(Gdk.WindowTypeHint.TOOLTIP)  # Make it look like a tooltip
        self.display_popup.set_default_size(200, 120)
        self.display_popup.set_transient_for(self.window)
        self.display_popup.set_modal(False)  # Don't block interaction
        self.display_popup.set_decorated(False)
        self.display_popup.set_keep_above(True)
        self.display_popup.set_skip_taskbar_hint(True)
        self.display_popup.set_skip_pager_hint(True)
        self.display_popup.get_style_context().add_class("dropdown-menu")
        
        # Create a scrolled window for the display list
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_min_content_height(80)
        scrolled_window.set_max_content_height(120)
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        self.display_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.display_list.set_margin_start(12)
        self.display_list.set_margin_end(12)
        self.display_list.set_margin_top(12)
        self.display_list.set_margin_bottom(12)
        
        scrolled_window.add(self.display_list)
        self.display_popup.add(scrolled_window)
        
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
        self.recording_mode = 'area'  # Default to area mode
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0

        # Log initialization
        self.update_record_button_state()  # Set initial button state
        logger.info("Capty Screen Recorder initialized")

    def position_display_popup(self):
        """Position the display popup like a dropdown below the display button"""
        try:
            # Get the position of the main window
            main_x, main_y = self.window.get_position()
            
            # Get the display button position relative to the main window
            # Since the display button is the first scope button, estimate its position
            # Main window has margins, and display button is after close button
            button_x = main_x + 12 + 24 + 6  # margin + close button width + spacing
            button_y = main_y + 8  # margin top
            button_width = 60  # display button width
            button_height = 30  # display button height
            
            # Position popup directly below the display button
            popup_x = button_x
            popup_y = button_y + button_height + 5  # 5px gap
            
            # Ensure popup stays on screen
            screen = Gdk.Screen.get_default()
            if screen:
                screen_width = screen.get_width()
                screen_height = screen.get_height()
                
                # If popup would go off the right edge, align to right edge of button
                if popup_x + 200 > screen_width:
                    popup_x = button_x + button_width - 200
                
                # If popup would go off the bottom, position above the button
                if popup_y + 120 > screen_height:
                    popup_y = button_y - 125  # 5px gap above
            
            self.display_popup.move(popup_x, popup_y)
            logger.info(f"Positioned display popup at ({popup_x}, {popup_y})")
        except Exception as e:
            logger.error(f"Error positioning display popup: {e}")

    def center_window_bottom(self):
        """Position window at bottom center of screen"""
        try:
            screen = Gdk.Screen.get_default()
            if screen:
                screen_width = screen.get_width()
                screen_height = screen.get_height()
                window_width = 500
                window_height = 50
                x = (screen_width - window_width) // 2
                y = screen_height - window_height - 50  # 50px from bottom
                self.window.move(x, y)
        except Exception as e:
            print(f"Error centering window: {e}")

    def on_window_button_press(self, widget, event):
        """Handle window dragging"""
        if event.button == 1:  # Left mouse button
            self.dragging = True
            pos = self.window.get_position()
            self.drag_start_x = event.x_root - pos[0]
            self.drag_start_y = event.y_root - pos[1]
        return False

    def on_window_button_release(self, widget, event):
        """Handle window dragging stop"""
        if event.button == 1:  # Left mouse button
            self.dragging = False
        return False

    def on_window_motion(self, widget, event):
        """Handle window dragging"""
        if self.dragging and self.window:
            try:
                x = event.x_root - self.drag_start_x
                y = event.y_root - self.drag_start_y
                # Ensure window stays on screen
                screen = Gdk.Screen.get_default()
                if screen:
                    max_x = screen.get_width() - self.window.get_allocated_width()
                    max_y = screen.get_height() - self.window.get_allocated_height()
                    x = max(0, min(x, max_x))
                    y = max(0, min(y, max_y))
                self.window.move(x, y)
            except Exception as e:
                print(f"Dragging error: {e}")
                self.dragging = False
        return False

    def get_available_displays(self):
        """Get list of available displays"""
        try:
            # Use xrandr --query to get display information (cleaner output)
            result = subprocess.run(["xrandr", "--query"], 
                                  capture_output=True, text=True, check=True)
            displays = []
            lines = result.stdout.strip().split('\n')
            
            for line in lines:
                if " connected " in line:
                    parts = line.split()
                    display_name = parts[0]  # This is the actual display name like HDMI-0, DP-2
                    
                    # Extract resolution and position from the line
                    resolution = "1920x1080"  # Default
                    x_offset = 0
                    y_offset = 0
                    
                    for part in parts:
                        if 'x' in part and part[0].isdigit():
                            # Parse the geometry part (e.g., "2560x1080+1920+0")
                            geometry_parts = part.split('+')
                            if len(geometry_parts) >= 3:
                                resolution = geometry_parts[0]
                                x_offset = int(geometry_parts[1])
                                y_offset = int(geometry_parts[2])
                            break
                    
                    displays.append({
                        'name': display_name,
                        'resolution': resolution,
                        'x_offset': x_offset,
                        'y_offset': y_offset,
                        'full_name': f"{display_name} ({resolution})"
                    })
            
            logger.info(f"Found {len(displays)} displays: {displays}")
            return displays
        except Exception as e:
            logger.error(f"Error getting displays: {e}")
            return [{'name': 'default', 'resolution': '1920x1080', 'full_name': 'Default Display'}]

    def populate_display_list(self):
        """Populate the display dropdown list"""
        logger.info(f"Populating display list with {len(self.displays)} displays")
        
        for child in self.display_list.get_children():
            self.display_list.remove(child)
        
        for display in self.displays:
            btn = Gtk.Button(label=display['full_name'])
            btn.set_size_request(180, 30)  # Set button size
            btn.get_style_context().add_class("dropdown-item")
            btn.connect("clicked", self.on_display_selected, display)
            self.display_list.pack_start(btn, False, False, 0)
            logger.info(f"Added display button: {display['full_name']}")
        
        self.display_list.show_all()
        logger.info(f"Display list populated with {len(self.displays)} items")

    def on_display_clicked(self, button):
        """Handle display button click"""
        logger.info("Display button clicked")
        self.recording_mode = 'display'
        
        # Position the popup near the display button
        self.position_display_popup()
        self.display_popup.show_all()

    def on_display_selected(self, button, display):
        """Handle display selection from dropdown"""
        self.selected_display = display
        self.display_btn.set_label(f"Display: {display['name']}")
        self.display_popup.hide()
        logger.info(f"Display selected: {display['name']} ({display['resolution']})")
        self.status.set_text(f"Selected display: {display['name']}")
        
        # Clear area selection when switching to display mode
        self.clear_area_selection()
        
        self.update_record_button_state()

    def on_area_clicked(self, button):
        """Handle area selection"""
        logger.info("Area button clicked")
        self.recording_mode = 'area'
        
        # Clear display selection when switching to area mode
        self.clear_display_selection()
        
        # Clear any existing area selection before starting new one
        self.clear_area_selection()
        
        self.select_area()

    def on_mic_toggle(self, button):
        """Toggle microphone recording"""
        self.mic_enabled = not self.mic_enabled
        if self.mic_enabled:
            button.set_label("🎤 ON")
            button.get_style_context().remove_class("inactive")
            button.get_style_context().add_class("active")
            logger.info("Microphone enabled")
        else:
            button.set_label("🎤 OFF")
            button.get_style_context().remove_class("active")
            button.get_style_context().add_class("inactive")
            logger.info("Microphone disabled")

    def on_system_audio_toggle(self, button):
        """Toggle system audio recording"""
        self.system_audio_enabled = not self.system_audio_enabled
        if self.system_audio_enabled:
            button.set_label("🔊 ON")
            button.get_style_context().remove_class("inactive")
            button.get_style_context().add_class("active")
            logger.info("System audio enabled")
        else:
            button.set_label("🔊 OFF")
            button.get_style_context().remove_class("active")
            button.get_style_context().add_class("inactive")
            logger.info("System audio disabled")

    def on_settings_clicked(self, button):
        """Handle settings button click"""
        logger.info("Settings button clicked")
        self.settings_popup.show_all()

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
            self.update_record_button_state()
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Area selection error: {e}")
            self.status.set_text("Area selection failed")

    def show(self):
        self.window.show_all()

    def clear_area_selection(self):
        """Clear the area selection and hide the overlay"""
        self.selected = None
        if hasattr(self, 'overlay') and self.overlay:
            self.overlay.hide()
        logger.info("Area selection cleared")

    def clear_display_selection(self):
        """Clear the display selection and reset button text"""
        self.selected_display = None
        if hasattr(self, 'display_btn'):
            self.display_btn.set_label("Display")
        logger.info("Display selection cleared")

    def can_record(self):
        """Check if recording is possible"""
        if self.recording_mode == 'display':
            return self.selected_display is not None
        elif self.recording_mode == 'area':
            return self.selected is not None
        else:
            return False

    def update_record_button_state(self):
        """Update record button appearance based on recording state"""
        if self.ffproc:  # Currently recording
            self.record_btn.set_label("⏹ Stop")
            self.record_btn.get_style_context().remove_class("record-button")
            self.record_btn.get_style_context().remove_class("disabled-button")
            self.record_btn.get_style_context().add_class("stop-button")
            self.record_btn.set_sensitive(True)
        elif self.can_record():  # Can record
            self.record_btn.set_label("🔴 Record")
            self.record_btn.get_style_context().remove_class("stop-button")
            self.record_btn.get_style_context().remove_class("disabled-button")
            self.record_btn.get_style_context().add_class("record-button")
            self.record_btn.set_sensitive(True)
        else:  # Cannot record
            self.record_btn.set_label("🔴 Record")
            self.record_btn.get_style_context().remove_class("record-button")
            self.record_btn.get_style_context().remove_class("stop-button")
            self.record_btn.get_style_context().add_class("disabled-button")
            self.record_btn.set_sensitive(False)

    def on_record_clicked(self, btn):
        """Handle record/stop button click - toggles between record and stop"""
        if self.ffproc:  # Currently recording, so stop
            self._stop_recording()
            return
        
        # Check if we can record
        if not self.can_record():
            self.status.set_text("Please select a display or area first")
            logger.warning("No valid recording target selected")
            return
        
        # Not recording, so start recording
        logger.info("Record button clicked - starting recording")
        
        # Determine what to record based on mode
        if self.recording_mode == 'display':
            if not self.selected_display:
                self.status.set_text("Please select a display first")
                logger.warning("No display selected")
                return
            # For display recording, use the actual display geometry
            resolution_parts = self.selected_display['resolution'].split('x')
            width = int(resolution_parts[0])
            height = int(resolution_parts[1])
            x_offset = self.selected_display['x_offset']
            y_offset = self.selected_display['y_offset']
            
            self.selected = (x_offset, y_offset, width, height)
            logger.info(f"Recording display: {self.selected_display['name']} at ({x_offset}, {y_offset}) with size {width}x{height}")
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
        
        # Prevent overwrite with numbered suffixes
        counter = 1
        original_base_path = base_path
        while True:
            mp4_candidate = f"{base_path}.mp4"
            gif_candidate = f"{base_path}.gif"
            palette_candidate = f"{base_path}_palette.png"
            if os.path.exists(mp4_candidate) or os.path.exists(gif_candidate) or os.path.exists(palette_candidate):
                base_path = f"{original_base_path}({counter})"
                counter += 1
            else:
                break
            
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

        # Update UI - change button to stop state
        self.record_btn.set_label("⏹ Stop")
        self.record_btn.get_style_context().remove_class("record-button")
        self.record_btn.get_style_context().add_class("stop-button")
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
                GLib.idle_add(self.reset_recording_state)

        self.record_thread = Thread(target=record_worker, daemon=True)
        self.record_thread.start()

    def reset_recording_state(self):
        """Reset recording state and button"""
        self.ffproc = None
        self.record_thread = None
        self.update_record_button_state()

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
            # Reset state after stopping
            self.reset_recording_state()
        except Exception as e:
            logger.error(f"Stop error: {e}")
            try:
                self.ffproc.terminate()
                logger.info("Process terminated")
            except:
                logger.error("Failed to terminate process")
            # Reset state even if there was an error
            self.reset_recording_state()

    def on_record_finished(self, to_gif):
        """Handle recording completion"""
        logger.info("Recording finished")
        self.status.set_text("Recording finished")
        
        # Reset recording state
        self.ffproc = None
        self.record_thread = None
        
        # Reset button to record state
        self.record_btn.set_label("🔴 Record")
        self.record_btn.get_style_context().remove_class("stop-button")
        self.record_btn.get_style_context().add_class("record-button")

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

## Capty — simple area screen recorder for Linux (MP4/GIF)

Capty lets you quickly record a selected screen area to MP4 or GIF on Linux. It provides a tiny GTK window to pick a region, set a delay, choose FPS and format, then start/stop recording.

### Features
- **Area selection**: draw a rectangle using `slop`.
- **MP4 or GIF**: high‑quality MP4 (H.264) or animated GIF (palettegen + paletteuse, optional `gifsicle` optimization).
- **FPS control**: choose frames per second.
- **Delayed start**: countdown before recording begins.
- **Overlay**: subtle border overlay that is visible when selecting and after recording; hidden while recording so you can work normally.
- **Hotkey**: Ctrl+Alt+S to stop (when the Capty window has focus).
- **Saves to**: `~/Videos` (created if missing) with unique filenames.

### Requirements
Install runtime dependencies (Debian/Ubuntu):

```bash
sudo apt update
sudo apt install -y python3 python3-gi gir1.2-gtk-3.0 ffmpeg slop gifsicle
```

Notes:
- Capty uses FFmpeg's `x11grab`. It works best on X11. On Wayland, run an X11 session or ensure XWayland is available.

### Install

#### Option 1: From the bundled .deb
If you have `capty_0.1.0_amd64.deb` in this repo:

```bash
sudo apt install -y python3 python3-gi gir1.2-gtk-3.0 ffmpeg slop gifsicle
sudo dpkg -i capty_0.1.0_amd64.deb || sudo apt -f install -y
```

This installs a launcher and an executable `capty` under `/usr/local/bin/capty`.

#### Option 2: Run from source

```bash
sudo apt install -y python3 python3-gi gir1.2-gtk-3.0 ffmpeg slop gifsicle
python3 capty.py
```

Optional: create a desktop launcher manually

```bash
sudo install -m 0755 capty.py /usr/local/bin/capty
sudo install -m 0644 capty.desktop /usr/share/applications/capty.desktop
sudo update-desktop-database || true
```

### Usage
1. Launch Capty (from your app menu or by running `capty` / `python3 capty.py`).
2. Click **Select area** and draw the rectangle you want to record.
3. Set **Filename**, **Delay**, **Format** (MP4 or GIF), and **FPS**.
4. Click **Record**. After the countdown, recording starts.
5. Click **Stop** (or press Ctrl+Alt+S while the Capty window has focus).
6. Output is saved to `~/Videos` as either `.mp4` or `.gif`. A palette image is generated temporarily for GIFs.

Tips:
- If the chosen base filename already exists, a timestamp suffix is added automatically to avoid overwriting.
- If `gifsicle` is installed, GIFs are optimized automatically.

### Keyboard shortcuts
- **Ctrl+Alt+S**: Stop recording (Capty window must have focus).

### Troubleshooting
- **Wayland**: Capty records via `x11grab`. Use an X11 session or ensure XWayland is running. On strict Wayland sessions, native screen capture may not work.
- **Selection tool not found**: Ensure `slop` is installed.
- **No video output or zero‑byte file**: Check FFmpeg is installed and `DISPLAY` points to your X server (e.g., `:0`).
- **Cannot write to Videos**: Capty creates `~/Videos` automatically, but verify disk permissions/space.

### Packaging (optional, using build script)
If you want to build your own `.deb` locally with names matching this repo:

```bash
# Make the build script executable and run it
chmod +x build_deb.sh
./build_deb.sh 0.1.0
```

The build script will:
- Install fpm if not already installed
- Set proper package metadata (description, maintainer, license, etc.)
- Create a properly named .deb package
- Show package information after building

You can specify a custom version: `./build_deb.sh 1.2.3`

### Project structure
- `capty.py`: main GTK application.
- `capty.desktop`: desktop launcher entry (Exec: `/usr/local/bin/capty`).
- `icon.png`: optional icon if you package it.
- `build_deb.sh`: build script for creating .deb packages with proper metadata.
- `capty_0.1.0_amd64.deb`: prebuilt Debian package (if present).

### License
Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)

Copyright (c) 2024 Capty

This work is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License. To view a copy of this license, visit:
https://creativecommons.org/licenses/by-nc/4.0/

or send a letter to:
Creative Commons
PO Box 1866
Mountain View, CA 94042
USA

You are free to:
- Share — copy and redistribute the material in any medium or format
- Adapt — remix, transform, and build upon the material

Under the following terms:
- Attribution — You must give appropriate credit, provide a link to the license, and indicate if changes were made. You may do so in any reasonable manner, but not in any way that suggests the licensor endorses you or your use.
- NonCommercial — You may not use the material for commercial purposes.

No additional restrictions — You may not apply legal terms or technological measures that legally restrict others from doing anything the license permits.

Notices:
You do not have to comply with the license for elements of the material in the public domain or where your use is permitted by an applicable exception or limitation.

No warranties are given. The license may not give you all of the permissions necessary for your intended use. For example, other rights such as publicity, privacy, or moral rights may limit how you use the material.
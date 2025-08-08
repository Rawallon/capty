#!/bin/bash

# Build script for capty .deb package
# This script creates a .deb package with proper metadata

set -e

# Check if fpm is installed
if ! command -v fpm &> /dev/null; then
    echo "fpm is not installed. Installing..."
    sudo apt-get update
    sudo apt-get install -y ruby ruby-dev build-essential
    sudo gem install --no-document fpm
fi

# Set version (you can change this)
VERSION=${1:-0.1.0}

echo "Building capty version $VERSION..."

# Make sure capty.py is executable
chmod +x capty.py

# Build the package with proper metadata
fpm -s dir -t deb -n capty -v "$VERSION" \
  --depends "python3" \
  --depends "python3-gi" \
  --depends "gir1.2-gtk-3.0" \
  --depends "ffmpeg" \
  --depends "slop" \
  --depends "gifsicle" \
  --maintainer "rawallon@wallon" \
  --description "Capty is a simple area screen recorder for Linux that lets you quickly record a selected screen area to MP4 or GIF. It provides a tiny GTK window to pick a region, set a delay, choose FPS and format, then start/stop recording. Features include area selection, MP4/GIF output, FPS control, delayed start, overlay, and hotkey support." \
  --url "https://github.com/rawallon/screen-recorder" \
  --category "Utility" \
  --license "CC-BY-NC-4.0" \
  --vendor "rawallon" \
  ./capty.py=/usr/local/bin/capty \
  ./capty.desktop=/usr/share/applications/capty.desktop \
  ./icon.png=/usr/share/pixmaps/capty.png

# Rename the package to match the expected format (if it's not already named correctly)
if [ -f "capty_${VERSION}_amd64.deb" ]; then
    echo "Package already has correct name"
else
    mv capty_*_amd64.deb capty_${VERSION}_amd64.deb
fi

echo "Package built: capty_${VERSION}_amd64.deb"
echo "Package info:"
dpkg-deb -I capty_${VERSION}_amd64.deb

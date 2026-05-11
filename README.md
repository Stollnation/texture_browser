# Texture Browser

A lightweight Windows-oriented texture and media browser built with Python and PySide6. It scans folders in the background, groups image sequences, caches thumbnails on disk, and opens a simple internal viewer for images, sequences, and video items.

## Features

- Windows-style folder tree with a persistent favorites section.
- Recursive media scanning with background workers.
- Thumbnail grid with Tiny, Small, Medium, and Large sizing.
- FBX-only filter for model browsing.
- Image sequence grouping for names like `smoke_0001.tga` and `wood_diffuse.1001.exr`.
- Search filtering across name, folder path, extension, and sequence pattern.
- Disk-based thumbnail cache keyed by file path, size, modified time, and file size.
- Context menu actions for opening Explorer, copying the file path, and copying the folder path.
- Internal image viewer with fit-to-window zoom and frame stepping for sequences.
- Video double-click handoff to VLC.
- FBX double-click handoff to Blender or the default FBX app.
- (and more!)

## Project Layout

```text
texture_browser/
  main.py
  app/
    __init__.py
    favorites.py
    folder_tree.py
    main_window.py
    models.py
    scanner.py
    sequence_detector.py
    thumbnail_grid.py
    thumbnailer.py
    utils.py
    viewer.py
  requirements.txt
  README.md
```

## Install

1. Create and activate a virtual environment.
2. Install the base dependencies:

```powershell
cd "C:\Users\jonis\Documents\New project\texture_browser"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Install optional dependencies if you want broader preview support:

```powershell
pip install imageio psd-tools opencv-python-headless
```

## Run

```powershell
cd "C:\Users\jonis\Documents\New project\texture_browser"
python main.py
```

## Format Support

Fully supported with the base install:

- `.png`
- `.jpg`, `.jpeg`
- `.bmp`
- `.gif`
- `.tif`, `.tiff` when Pillow can decode them

Supported when optional libraries are available:

- `.tga`, `.hdr`, `.exr`: usually through `imageio` and its backend support
- `.psd`: through `psd-tools`
- `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm` thumbnail extraction: through `opencv-python-headless`
- `.fbx`: listed in the browser with a model placeholder; double-click opens Blender when available

Graceful fallback behavior:

- Unsupported or unreadable files still appear in the browser.
- If a preview cannot be generated, the app shows a placeholder tile with the file extension.
- Corrupt files should not crash the app; preview generation failures fall back to placeholders.

## Notes

- Favorites and UI preferences are stored with `QSettings`.
- Thumbnail cache files are stored under the app data directory used by Qt for the current user.
- Video playback is not included in this first version. Videos open in the internal viewer with file information and preview imagery where thumbnail extraction succeeds.
- The scan cancel action is cooperative. Large directory walks stop on the next cancel checkpoint.

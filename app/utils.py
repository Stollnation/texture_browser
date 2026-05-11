from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from app.models import MediaItem

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".tga",
    ".psd",
    ".exr",
    ".hdr",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
}

MODEL_EXTENSIONS = {
    ".fbx",
}


def app_data_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = app_data_dir() / "thumb_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_extension(path: Path) -> str:
    return path.suffix.lower()


def is_supported_media(path: Path) -> bool:
    ext = normalize_extension(path)
    return ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS or ext in MODEL_EXTENSIONS


def is_drive_root(path: Path) -> bool:
    return bool(path.drive and path.root and path.parent == path)


def media_kind_for_path(path: Path) -> str:
    ext = normalize_extension(path)
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in MODEL_EXTENSIONS:
        return "model"
    return "image"


def cache_key(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def format_type_label(item: MediaItem) -> str:
    if item.is_sequence and item.sequence:
        return f"Sequence {item.extension} [{item.sequence.frame_range_label}]"
    if item.is_video:
        return f"Video {item.extension}"
    if item.is_model:
        return f"Model {item.extension}"
    return f"Image {item.extension}"


def open_in_explorer(path: Path) -> None:
    try:
        subprocess.Popen(["explorer", "/select,", os.fspath(path)])
    except OSError:
        subprocess.Popen(["explorer", os.fspath(path.parent)])


def open_folder_in_explorer(path: Path) -> None:
    subprocess.Popen(["explorer", os.fspath(path)])


def find_windows_photo_viewer() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Windows Photo Viewer" / "PhotoViewer.dll",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Windows Photo Viewer" / "PhotoViewer.dll",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def open_image_in_default_viewer(path: Path) -> bool:
    photo_viewer = find_windows_photo_viewer()
    if photo_viewer is not None:
        try:
            subprocess.Popen(
                [
                    "rundll32.exe",
                    f"{os.fspath(photo_viewer)},",
                    "ImageView_Fullscreen",
                    os.fspath(path),
                ]
            )
            return True
        except OSError:
            pass

    if hasattr(os, "startfile"):
        try:
            os.startfile(os.fspath(path))
            return True
        except OSError:
            pass

    try:
        subprocess.Popen(["explorer", os.fspath(path)])
        return True
    except OSError:
        return False


def find_vlc_executable() -> Path | None:
    path = shutil.which("vlc")
    if path:
        return Path(path)

    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "VideoLAN" / "VLC" / "vlc.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "VideoLAN" / "VLC" / "vlc.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def open_video_in_vlc(path: Path) -> bool:
    vlc = find_vlc_executable()
    if vlc is None:
        return False
    subprocess.Popen([os.fspath(vlc), os.fspath(path)])
    return True


def find_blender_executable() -> Path | None:
    path = shutil.which("blender")
    if path:
        return Path(path)

    roots = [
        Path(os.environ.get("ProgramFiles", "")) / "Blender Foundation",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Blender Foundation",
    ]
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        candidates.extend(root.glob("Blender *\\blender.exe"))
    candidates.sort(reverse=True)
    return candidates[0] if candidates else None


def open_fbx_in_viewer(path: Path) -> str | None:
    blender = find_blender_executable()
    if blender is not None:
        resolved_path = str(path.resolve())
        log_path = Path(tempfile.gettempdir()) / "texture_browser_blender_fbx.log"
        script = f"""
import os
import sys
import traceback
from pathlib import Path

import bpy

fbx_path = {resolved_path!r}
log_path = {str(log_path)!r}


def log(message):
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(message + "\\n")


try:
    log("Opening FBX: " + fbx_path)
    bpy.context.preferences.view.show_splash = False

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    before = set(bpy.context.scene.objects)
    try:
        bpy.ops.import_scene.fbx(filepath=fbx_path, use_anim=False, use_image_search=True)
        log("Imported with import_scene.fbx")
    except Exception:
        log("import_scene.fbx failed; trying wm.fbx_import")
        log(traceback.format_exc())
        bpy.ops.wm.fbx_import(filepath=fbx_path, use_anim=False)
        log("Imported with wm.fbx_import")

    imported_objects = [obj for obj in bpy.context.scene.objects if obj not in before]
    if not imported_objects:
        imported_objects = list(bpy.context.scene.objects)

    bpy.ops.object.select_all(action='DESELECT')
    for obj in imported_objects:
        obj.select_set(True)
    if imported_objects:
        bpy.context.view_layer.objects.active = imported_objects[0]
    log("Imported object count: " + str(len(imported_objects)))


    def frame_imported_model():
        bpy.context.preferences.view.show_splash = False
        for window in bpy.context.window_manager.windows:
            screen = window.screen
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                region = next((region for region in area.regions if region.type == 'WINDOW'), None)
                if region is None:
                    continue
                space = next((space for space in area.spaces if space.type == 'VIEW_3D'), None)
                if space is not None:
                    space.shading.type = 'MATERIAL'
                with bpy.context.temp_override(window=window, screen=screen, area=area, region=region):
                    bpy.ops.view3d.view_selected(use_all_regions=False)
                log("Framed imported model")
                return None
        return 0.25

    bpy.app.timers.register(frame_imported_model, first_interval=0.5)
except Exception:
    log("FBX import failed")
    log(traceback.format_exc())
    raise
"""
        script_file = Path(tempfile.gettempdir()) / "texture_browser_open_fbx.py"
        script_file.write_text(script, encoding="utf-8")
        subprocess.Popen(
            [
                os.fspath(blender),
                "--factory-startup",
                "--python-exit-code",
                "9",
                "--python",
                os.fspath(script_file),
            ],
            cwd=os.fspath(path.parent),
        )
        return f"Blender ({blender.parent.name})"

    if hasattr(os, "startfile"):
        os.startfile(os.fspath(path))
        return "the default FBX app"
    return None

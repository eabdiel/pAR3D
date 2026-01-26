# ================================================================
# pAR3D by ProgreTech
# Version: 0.1.0
# Last updated: 2026-01-26
#
# Copyright:
#   Developed by Edwin Rodriguez (Project ProgreTech)
#   GitHub: https://github.com/eabdiel  (repo: pAR3D)
#
# Notes:
# - Personal edition (no company branding)
# - Canonical filename: pAR3D.py
# - Default High Performance priority
# - Tray Priority toggles (High / Normal / Eco)
# - Persisted user settings (JSON)
# - Quiet OpenCV camera probing warnings (probe only when camera source is selected)
# ================================================================

#!/usr/bin/env python
# =============================================================================
#  pAR3D by ProgreTech — Offline-first SBS 3D Prototype (Depth Anything V2)
#
#  Developed by: Edwin Rodriguez (Project ProgreTech)
#  GitHub:       https://github.com/eabdiel  (repo: pAR3D)
#  Date:         2026-01-26
#
#  Description:
#    Converts a live video source (Desktop monitor or Camera feed) into a full
#    Side-By-Side (SBS) stereo feed for AR glasses by estimating per-frame
#    monocular depth (Depth Anything V2 via Hugging Face Transformers) and
#    synthesizing stereo views using depth-image-based rendering (DIBR).
#
#  Icon assets:
#    - Place the PNG and ICO inside: ./assets/
#      * PNG: assets\ogre-icon-1-150x150.png   (tray icon + in-window floating icon)
#      * ICO: assets\pAR3D.ico                 (recommended for packaged .exe)
#
#  Controls:
#    - Tray menu (taskbar): Start/Stop, Source Desktop/Camera, Select monitor/camera,
#      Toggle fullscreen, Quit, About.
#    - In the window: Press Q or ESC to quit, F to toggle fullscreen.
#    - Double-click the output window while in fullscreen to return to windowed mode.
# =============================================================================
import os
import sys
import time
import threading
import traceback
import json
from pathlib import Path
from dataclasses import dataclass, asdict

import numpy as np
import cv2
import mss
from PIL import Image

import torch
from transformers import AutoModelForDepthEstimation
try:
    from transformers import AutoImageProcessor
    IMAGE_PROCESSOR_CLS = AutoImageProcessor
except Exception:
    from transformers import AutoFeatureExtractor
    IMAGE_PROCESSOR_CLS = AutoFeatureExtractor

# Tray icon (taskbar)
import pystray
from pystray import MenuItem as Item


# Silence HF symlink warning on Windows (caching still works without symlinks)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import argparse


APP_NAME = "pAR3D by ProgreTech"
APP_VERSION = "0.1.0"
# Multiple Models available - Small, Base and Large; visit open source project https://huggingface.co/depth-anything/collections
# Default is depth-anything/Depth-Anything-V2-Base-hf
# try depth-anything/Depth-Anything-V2-Small-hf or depth-anything/Depth-Anything-V2-Large-hf
MODEL_ID_DEFAULT = "depth-anything/Depth-Anything-V2-Base-hf"
ICON_PNG_DEFAULT = os.path.join("assets", "ogre-icon-1-150x150.png")
ICON_ICO_DEFAULT = os.path.join("assets", "pAR3D.ico")
# Floating icon settings (bottom-right of the SBS output)
FLOATING_ICON_CORNER = "br"
FLOATING_ICON_TARGET_H = 64  # pixels
# ---------------------------------------------------------------------------
# Process priority (Windows)
# ---------------------------------------------------------------------------
def _win_set_priority_class(priority_class: int) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentProcess()
        ok = kernel32.SetPriorityClass(handle, priority_class)
        return bool(ok)
    except Exception:
        return False


def set_process_priority(mode: str) -> bool:
    """Best-effort process priority adjustment.

    mode:
      - "high":   High priority (recommended for best feed performance)
      - "normal": Normal priority (balanced)
      - "below":  Below-normal priority (eco / lowest impact)
    """
    mode = (mode or "").strip().lower()
    if os.name != "nt":
        return False

    # Windows priority classes (kernel32 SetPriorityClass)
    HIGH_PRIORITY_CLASS = 0x00000080
    NORMAL_PRIORITY_CLASS = 0x00000020
    BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

    if mode == "high":
        return _win_set_priority_class(HIGH_PRIORITY_CLASS)
    if mode == "below":
        return _win_set_priority_class(BELOW_NORMAL_PRIORITY_CLASS)
    return _win_set_priority_class(NORMAL_PRIORITY_CLASS)


def set_priority_mode(mode: str):
    """Update config + apply process priority immediately."""
    with STATE.lock:
        STATE.cfg.priority_mode = (mode or "normal").strip().lower()
        mode_now = STATE.cfg.priority_mode
    set_process_priority(mode_now)

    persist_config()


@dataclass
class AppConfig:
    source: str = "desktop"     # "desktop" or "camera"
    monitor_index: int = 1      # MSS monitor index (1=primary)
    camera_index: int = 0
    max_disp: float = 30.0
    gamma: float = 1.3
    smooth: float = 0.88
    invert_depth: bool = False
    inpaint: bool = False
    fullscreen: bool = False
    scale: float = 0.75         # downscale frames for speed
    logo_path: str = ""         # optional
    FLOATING_ICON_CORNER: str = "br"       # br/bl/tr/tl
    model_id: str = MODEL_ID_DEFAULT
    target_fps: int = 15        # limit UI update rate to reduce CPU starvation
    depth_every_n: int = 2     # run depth inference every N frames (re-use depth between)
    priority_mode: str = "high"  # "high" (default), "normal", "below"


class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = True          # whole app running
        self.processing = True       # start enabled by default
        self.cfg = AppConfig()
        self.request_restart_window = False
        self.last_error = ""

STATE = SharedState()


def alpha_blend(overlay_bgr, base_bgr, x, y, alpha):
    h, w = overlay_bgr.shape[:2]
    H, W = base_bgr.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(W, x + w), min(H, y + h)
    if x1 >= x2 or y1 >= y2:
        return base_bgr
    roi = base_bgr[y1:y2, x1:x2]
    ov = overlay_bgr[(y1 - y):(y2 - y), (x1 - x):(x2 - x)]
    blended = cv2.addWeighted(ov, alpha, roi, 1 - alpha, 0)
    base_bgr[y1:y2, x1:x2] = blended
    return base_bgr


def load_floating_icon_rgba(path):
    if not path:
        return None
    if not os.path.exists(path):
        return None
    logo = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if logo is None:
        return None
    if logo.ndim == 3 and logo.shape[2] == 3:
        a = np.full((logo.shape[0], logo.shape[1], 1), 255, dtype=logo.dtype)
        logo = np.concatenate([logo, a], axis=2)
    if logo.ndim != 3 or logo.shape[2] != 4:
        return None
    return logo



def overlay_floating_icon(img_bgr, icon_rgba, corner="br", target_h=64):
    """Overlay a small floating icon in the output window (no text watermark)."""
    if icon_rgba is None:
        return img_bgr
    h, w = img_bgr.shape[:2]
    pad = 14

    # Ensure RGBA
    if icon_rgba.ndim != 3 or icon_rgba.shape[2] != 4:
        return img_bgr

    ratio = float(target_h) / float(icon_rgba.shape[0])
    iw = max(1, int(icon_rgba.shape[1] * ratio))
    ih = max(1, int(icon_rgba.shape[0] * ratio))
    icon_rs = cv2.resize(icon_rgba, (iw, ih), interpolation=cv2.INTER_AREA)

    if corner == "br":
        x0 = w - iw - pad
        y0 = h - ih - pad
    elif corner == "bl":
        x0 = pad
        y0 = h - ih - pad
    elif corner == "tr":
        x0 = w - iw - pad
        y0 = pad
    else:
        x0 = pad
        y0 = pad

    x0 = max(0, min(w - iw, x0))
    y0 = max(0, min(h - ih, y0))

    icon_bgr = icon_rs[:, :, :3].astype(np.float32)
    icon_a = (icon_rs[:, :, 3].astype(np.float32) / 255.0)[:, :, None]

    roi = img_bgr[y0:y0 + ih, x0:x0 + iw].astype(np.float32)
    comp = icon_bgr * icon_a + roi * (1.0 - icon_a)
    img_bgr[y0:y0 + ih, x0:x0 + iw] = comp.astype(np.uint8)
    return img_bgr


def normalize_depth(d, eps=1e-6):
    dmin = float(np.min(d))
    dmax = float(np.max(d))
    if (dmax - dmin) < eps:
        return np.zeros_like(d, dtype=np.float32)
    return (d - dmin) / (dmax - dmin)


def make_stereo_sbs(frame_bgr, depth_norm, max_disp_px=30.0, gamma=1.3, inpaint=False):
    h, w = frame_bgr.shape[:2]
    disp = ((1.0 - depth_norm) ** gamma) * max_disp_px
    disp = disp.astype(np.float32)

    xs = np.tile(np.arange(w, dtype=np.float32), (h, 1))
    ys = np.tile(np.arange(h, dtype=np.float32).reshape(h, 1), (1, w))

    shift = disp * 0.5
    map_x_left = xs + shift
    map_x_right = xs - shift

    left = cv2.remap(frame_bgr, map_x_left, ys, interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    right = cv2.remap(frame_bgr, map_x_right, ys, interpolation=cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))

    if inpaint:
        left_mask = ((map_x_left < 0) | (map_x_left >= (w - 1))).astype(np.uint8) * 255
        right_mask = ((map_x_right < 0) | (map_x_right >= (w - 1))).astype(np.uint8) * 255
        left = cv2.inpaint(left, left_mask, inpaintRadius=2, flags=cv2.INPAINT_TELEA)
        right = cv2.inpaint(right, right_mask, inpaintRadius=2, flags=cv2.INPAINT_TELEA)

    return np.hstack([left, right])


def desktop_grab(mon):
    with mss.mss() as sct:
        while True:
            img = np.array(sct.grab(mon))  # BGRA
            yield cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def camera_grab(index):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {index}")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame
    finally:
        cap.release()


def list_monitors():
    with mss.mss() as sct:
        return sct.monitors  # index 0 is "all"


def probe_cameras(max_index=8):
    """Best-effort camera probe.

    Notes:
      - OpenCV can log warnings on Windows when probing non-existent/blocked devices.
      - We only call this when camera mode is enabled (see make_menu()).
    """
    available = []
    backends = [getattr(cv2, "CAP_MSMF", None), cv2.CAP_DSHOW]
    backends = [b for b in backends if b is not None]
    for i in range(max_index):
        opened = False
        for be in backends:
            cap = cv2.VideoCapture(i, be)
            if cap.isOpened():
                opened = True
                cap.release()
                break
            cap.release()
        if opened:
            available.append(i)
    return available


class DepthAnything:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.use_amp = (self.device.type == "cuda")
        self.processor = None
        self.model = None

    def _load_local_only(self):
        self.processor = IMAGE_PROCESSOR_CLS.from_pretrained(self.model_id, local_files_only=True)
        self.model = AutoModelForDepthEstimation.from_pretrained(self.model_id, local_files_only=True)

    def _load_with_download(self):
        self.processor = IMAGE_PROCESSOR_CLS.from_pretrained(self.model_id)
        self.model = AutoModelForDepthEstimation.from_pretrained(self.model_id)

    def load(self):
        # Try offline/local cache first
        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            self._load_local_only()
            mode = "offline-cache"
        except Exception:
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            self._load_with_download()
            mode = "downloaded"

        self.model.to(self.device)
        self.model.eval()
        return mode, str(self.device)

    @torch.no_grad()
    def infer(self, frame_bgr: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        inputs = self.processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        if self.use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                outputs = self.model(**inputs)
        else:
            outputs = self.model(**inputs)

        predicted_depth = outputs.predicted_depth
        H, W = frame_bgr.shape[:2]
        prediction = torch.nn.functional.interpolate(
            predicted_depth.unsqueeze(1),
            size=(H, W),
            mode="bicubic",
            align_corners=False,
        ).squeeze(1).squeeze(0)

        return prediction.detach().float().cpu().numpy().astype(np.float32)


def build_icon_image():
    """Tray/taskbar icon image (PIL Image). Uses assets PNG when available."""
    try:
        if os.path.exists(ICON_PNG_DEFAULT):
            im = Image.open(ICON_PNG_DEFAULT).convert("RGBA")
            im = im.resize((64, 64), resample=Image.LANCZOS)
            return im
    except Exception:
        pass

    # Fallback: simple generated icon
    img = np.zeros((64, 64, 4), dtype=np.uint8)
    img[:, :, 3] = 255
    cv2.putText(img, "3D", (8, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 255, 255), 3, cv2.LINE_AA)
    return Image.fromarray(img, mode="RGBA")


def set_source(src: str):
    with STATE.lock:
        STATE.cfg.source = src
        STATE.request_restart_window = True


    persist_config()

def set_monitor(idx: int):
    with STATE.lock:
        STATE.cfg.monitor_index = idx
        STATE.request_restart_window = True


    persist_config()

def set_camera(idx: int):
    with STATE.lock:
        STATE.cfg.camera_index = idx
        STATE.request_restart_window = True


    persist_config()

def toggle_fullscreen():
    with STATE.lock:
        STATE.cfg.fullscreen = not STATE.cfg.fullscreen
        STATE.request_restart_window = True


    persist_config()

def quit_app(icon: pystray.Icon, _item):
    with STATE.lock:
        STATE.running = False
        STATE.processing = False
    icon.stop()


def menu_start_stop():
    def _action(icon, item):
        with STATE.lock:
            STATE.processing = not STATE.processing
    return _action


def make_menu():
    mons = list_monitors()

    def _monitor_action(idx: int):
        # pystray actions must accept (icon, item) or (item)
        return lambda icon, item: set_monitor(idx)

    def _camera_action(idx: int):
        return lambda icon, item: set_camera(idx)

    monitor_items = []
    for i in range(1, len(mons)):
        name = f"Monitor {i} ({mons[i]['width']}x{mons[i]['height']})"
        monitor_items.append(Item(name, _monitor_action(i)))

    cams = []
    # Only probe cameras when camera mode is enabled; probing can produce noisy OpenCV warnings on locked-down laptops.
    if STATE.cfg.source == "camera":
        cams = probe_cameras(max_index=4)
    if not cams:
        cams = [0]
    camera_items = [Item(f"Camera {i}", _camera_action(i)) for i in cams]

    return pystray.Menu(
        Item(lambda item: "Stop" if STATE.processing else "Start", menu_start_stop()),
        Item("Source: Desktop", lambda icon, item: set_source("desktop"),
             checked=lambda item: STATE.cfg.source == "desktop"),
        Item("Source: Camera Feed", lambda icon, item: set_source("camera"),
             checked=lambda item: STATE.cfg.source == "camera"),
        Item("Select Desktop Monitor", pystray.Menu(*monitor_items)),
        Item("Select Camera Index", pystray.Menu(*camera_items)),
        Item("Priority Mode", pystray.Menu(
            Item("Performance (High)", lambda icon, item: set_priority_mode("high"),
                 checked=lambda item: STATE.cfg.priority_mode == "high"),
            Item("Balanced (Normal)", lambda icon, item: set_priority_mode("normal"),
                 checked=lambda item: STATE.cfg.priority_mode == "normal"),
            Item("Eco (Below Normal)", lambda icon, item: set_priority_mode("below"),
                 checked=lambda item: STATE.cfg.priority_mode == "below"),
        )),
        Item("Toggle Fullscreen", lambda icon, item: toggle_fullscreen()),
        Item("About", show_about),
        Item("Quit", lambda icon, item: quit_app(icon, item))
    )


def tray_thread():

    icon = pystray.Icon(APP_NAME, build_icon_image(), APP_NAME, make_menu())
    icon.run()


def configure_window(win_name: str, fullscreen: bool):
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win_name, cv2.WND_PROP_FULLSCREEN,
                          cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)


def parse_args_into_config():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--source", choices=["desktop", "camera"], default=None)
    ap.add_argument("--monitor", type=int, default=None)
    ap.add_argument("--camera", type=int, default=None)
    ap.add_argument("--logo", type=str, default=None)
    ap.add_argument("--corner", choices=["br", "bl", "tr", "tl"], default=None)
    ap.add_argument("--scale", type=float, default=None)
    ap.add_argument("--max-disp", type=float, default=None)
    ap.add_argument("--gamma", type=float, default=None)
    ap.add_argument("--smooth", type=float, default=None)
    ap.add_argument("--invert-depth", action="store_true")
    ap.add_argument("--inpaint", action="store_true")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--model-id", type=str, default=None)
    ap.add_argument("--target-fps", type=int, default=None)
    ap.add_argument("--depth-every", type=int, default=None)
    ap.add_argument("--priority", choices=["high", "normal", "below"], default=None)
    args = ap.parse_args()

    with STATE.lock:
        cfg = STATE.cfg
        if args.source is not None:
            cfg.source = args.source
        if args.monitor is not None:
            cfg.monitor_index = args.monitor
        if args.camera is not None:
            cfg.camera_index = args.camera
        if args.logo is not None:
            cfg.logo_path = args.logo
        if args.corner is not None:
            cfg.FLOATING_ICON_CORNER = args.corner
        if args.scale is not None:
            cfg.scale = args.scale
        if args.max_disp is not None:
            cfg.max_disp = args.max_disp
        if args.gamma is not None:
            cfg.gamma = args.gamma
        if args.smooth is not None:
            cfg.smooth = args.smooth
        if args.model_id is not None:
            cfg.model_id = args.model_id
        if args.target_fps is not None:
            cfg.target_fps = int(args.target_fps)
        if args.depth_every is not None:
            cfg.depth_every_n = max(1, int(args.depth_every))
        if args.priority is not None:
            cfg.priority_mode = args.priority
        if args.invert_depth:
            cfg.invert_depth = True
        if args.inpaint:
            cfg.inpaint = True
        if args.fullscreen:
            cfg.fullscreen = True


def main():
    # Load saved preferences first (then allow CLI overrides)
    saved = load_config()
    with STATE.lock:
        apply_dict_to_config(STATE.cfg, saved)

    # Allow CLI overrides (still fully optional)
    parse_args_into_config()

    with STATE.lock:
        if not STATE.cfg.logo_path:
            STATE.cfg.logo_path = os.environ.get("PAR3D_ICON", "")

    # Performance guardrails (helps reduce mouse/UI lag on CPU)
    try:
        cv2.setUseOptimized(True)
        # Avoid OpenCV oversubscribing threads; PyTorch will use its own.
        cv2.setNumThreads(0)
    except Exception:
        pass
    if not torch.cuda.is_available():
        try:
            # Keep some CPU headroom for Windows UI/mouse
            torch.set_num_threads(max(1, (os.cpu_count() or 4) // 2))
        except Exception:
            pass


    # Apply priority mode (default: high performance)
    with STATE.lock:
        _pmode = STATE.cfg.priority_mode
    set_process_priority(_pmode)

    # Start tray
    t = threading.Thread(target=tray_thread, daemon=True)
    t.start()

    # Load model offline-first
    with STATE.lock:
        model_id = STATE.cfg.model_id
    depth_model = DepthAnything(model_id=model_id)

    try:
        load_mode, device = depth_model.load()
        print(f"[{APP_NAME}] Depth model ready ({load_mode}) on {device} | model={model_id}")
    except Exception as e:
        print(f"[{APP_NAME}] Failed to load model: {e}")
        traceback.print_exc()
        return

    with STATE.lock:
        floating_icon_rgba = load_floating_icon_rgba(ICON_PNG_DEFAULT)

    win_name = f"{APP_NAME} — SBS Output"
    configure_window(win_name, fullscreen=STATE.cfg.fullscreen)

    fps = 0.0
    last_t = time.time()
    prev_depth = None
    frame_idx = 0
    last_depth_norm = None

    current_gen = None
    current_src = None
    current_sel = None

    while True:
        with STATE.lock:
            running = STATE.running
            processing = STATE.processing
            cfg = STATE.cfg
            restart = STATE.request_restart_window
            STATE.request_restart_window = False

        if not running:
            break

        if restart:
            try:
                configure_window(win_name, fullscreen=cfg.fullscreen)
            except Exception:
                pass
            current_gen = None
            current_src = None
            current_sel = None
            prev_depth = None
            frame_idx = 0
            last_depth_norm = None

        if not processing:
            idle = np.zeros((720, 1280, 3), dtype=np.uint8)
            cv2.putText(idle, f"{APP_NAME} (Stopped) - Use tray menu to Start",
                        (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
            idle = overlay_floating_icon(idle, floating_icon_rgba, text=WATERMARK_TEXT, corner=FLOATING_ICON_CORNER)
            cv2.imshow(win_name, idle)
            if (cv2.waitKey(30) & 0xFF) in (ord('q'), 27):
                with STATE.lock:
                    STATE.running = False
                    STATE.processing = False
                break
            continue

        desired_src = cfg.source
        desired_sel = cfg.monitor_index if desired_src == "desktop" else cfg.camera_index

        if current_gen is None or current_src != desired_src or current_sel != desired_sel:
            try:
                if desired_src == "desktop":
                    mons = list_monitors()
                    if desired_sel < 1 or desired_sel >= len(mons):
                        desired_sel = 1
                    mon = mons[desired_sel]
                    current_gen = desktop_grab(mon)
                else:
                    current_gen = camera_grab(desired_sel)
                current_src = desired_src
                current_sel = desired_sel
                prev_depth = None
                frame_idx = 0
                last_depth_norm = None
            except Exception as e:
                err = f"Source init failed ({desired_src} {desired_sel}): {e}"
                with STATE.lock:
                    STATE.last_error = err
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(frame, err, (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
                frame = overlay_floating_icon(frame, floating_icon_rgba, text=WATERMARK_TEXT, corner=FLOATING_ICON_CORNER)
                cv2.imshow(win_name, frame)
                cv2.waitKey(200)
                continue

        try:
            frame = next(current_gen)
        except StopIteration:
            current_gen = None
            continue
        except Exception:
            current_gen = None
            continue

        if cfg.scale and cfg.scale != 1.0:
            frame = cv2.resize(frame, None, fx=cfg.scale, fy=cfg.scale, interpolation=cv2.INTER_AREA)

        # Depth inference is the expensive step. On CPU, run it every N frames and reuse depth in-between.
        run_depth = (frame_idx % max(1, cfg.depth_every_n) == 0) or (last_depth_norm is None)
        if run_depth:
            try:
                depth = depth_model.infer(frame)
                depth_norm = normalize_depth(depth)
                last_depth_norm = depth_norm
            except Exception as e:
                err = f"Depth inference error: {e}"
                with STATE.lock:
                    STATE.last_error = err
                out = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(out, err, (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
                out = overlay_floating_icon(out, floating_icon_rgba, text=WATERMARK_TEXT, corner=FLOATING_ICON_CORNER)
                cv2.imshow(win_name, out)
                cv2.waitKey(100)
                continue
        else:
            depth_norm = last_depth_norm
        if cfg.invert_depth:
            depth_norm = 1.0 - depth_norm

        if prev_depth is None:
            depth_s = depth_norm
        else:
            depth_s = (cfg.smooth * prev_depth) + ((1.0 - cfg.smooth) * depth_norm)
        prev_depth = depth_s

        sbs = make_stereo_sbs(frame, depth_s, max_disp_px=cfg.max_disp, gamma=cfg.gamma, inpaint=cfg.inpaint)

        now = time.time()
        dt = now - last_t
        last_t = now
        if dt > 0:
            fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps > 0 else (1.0 / dt)

        out = sbs.copy()
        cv2.putText(out, f"{APP_NAME} | {current_src}:{current_sel} | FPS~{fps:.1f}",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        out = overlay_floating_icon(out, floating_icon_rgba, text=WATERMARK_TEXT, corner=FLOATING_ICON_CORNER)

        cv2.imshow(win_name, out)

        # Throttle to keep OS/UI responsive (especially on CPU)
        if cfg.target_fps and cfg.target_fps > 0:
            frame_time = 1.0 / float(cfg.target_fps)
            spent = time.time() - now
            if spent < frame_time:
                time.sleep(frame_time - spent)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            with STATE.lock:
                STATE.running = False
                STATE.processing = False
            break
        elif key == ord('f'):
            toggle_fullscreen()

        frame_idx += 1

    cv2.destroyAllWindows()


# -----------------------------
# Settings persistence (safe)
# -----------------------------
CONFIG_PATH = Path.home() / ".par3d_config.json"

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            return {}
    return {}

def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass

# -----------------------------
# About dialog helper
# -----------------------------

# -----------------------------
# Config helpers (persist user preferences)
# -----------------------------
def config_to_dict(cfg: "AppConfig") -> dict:
    try:
        return asdict(cfg)
    except Exception:
        # Fallback if dataclasses.asdict fails for any reason
        return cfg.__dict__.copy()

def apply_dict_to_config(cfg: "AppConfig", d: dict) -> None:
    if not isinstance(d, dict):
        return
    for k, v in d.items():
        if hasattr(cfg, k):
            try:
                setattr(cfg, k, v)
            except Exception:
                pass

def persist_config():
    with STATE.lock:
        cfg_dict = config_to_dict(STATE.cfg)
    save_config(cfg_dict)

def get_about_text():
    return (
        "pAR3D by ProgreTech
"
        "Version " + APP_VERSION + "

"
        "Developed by Edwin Rodriguez (Project ProgreTech)
"
        "GitHub: https://github.com/eabdiel (repo: pAR3D)

"
        "Side-by-side 3D screen depth visualization
"
        "CPU-first, CUDA-enabled when available"
    )

def show_about(icon=None, item=None):
    """Show a simple About dialog (non-blocking for the main OpenCV loop)."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(APP_NAME, get_about_text())
        root.destroy()
    except Exception:
        # If Tk isn't available (rare), print to console
        print(get_about_text())

if __name__ == "__main__":
    try:
        main()
    except ModuleNotFoundError as e:
        print(f"Missing dependency: {e}")
        print("Install requirements:")
        print("  pip install -r requirements.txt")
        raise

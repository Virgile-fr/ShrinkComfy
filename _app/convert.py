"""
Logique de conversion ComfyUI : PNG -> WEBP/JPG en preservant le workflow.

Convention EXIF compatible drag & drop ComfyUI :
  - prompt   -> 0x010f (Make)            prefixe "Prompt: "
  - workflow -> 0x010e (ImageDescription) prefixe "Workflow: "

Limitation : ComfyUI ne lit PAS le workflow depuis les WEBP lossless.
"""

import io
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from PIL import Image
import concurrent.futures
import threading as _thd


# -- Timestamps --------------------------------------------------------------

def _copy_timestamps(src_path: Path, dst_path: Path) -> None:
    """Copy atime/mtime (and ctime on Windows) from src to dst."""
    try:
        st = src_path.stat()
        os.utime(dst_path, (st.st_atime, st.st_mtime))
    except Exception:
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import ctypes.wintypes as wt
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateFileW(
            str(dst_path), 0x40000000, 0x00000001, None, 3, 0x80, None,
        )
        if handle == -1:
            return
        try:
            EPOCH_DIFF = 116444736000000000  # 100-ns from 1601-01-01 to 1970-01-01

            def _to_ft(t):
                v = int(t * 1e7) + EPOCH_DIFF
                ft = wt.FILETIME()
                ft.dwLowDateTime = v & 0xFFFFFFFF
                ft.dwHighDateTime = (v >> 32) & 0xFFFFFFFF
                return ft

            kernel32.SetFileTime(
                handle,
                ctypes.byref(_to_ft(st.st_ctime)),
                ctypes.byref(_to_ft(st.st_atime)),
                ctypes.byref(_to_ft(st.st_mtime)),
            )
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass


# -- Metadonnees ComfyUI -----------------------------------------------------

def extract_comfy_metadata(img):
    return {
        "prompt": img.info.get("prompt", ""),
        "workflow": img.info.get("workflow", ""),
    }


def has_comfy_metadata(path):
    """Retourne True si le PNG contient un workflow ou prompt ComfyUI."""
    try:
        img = Image.open(path)
        return bool(img.info.get("prompt") or img.info.get("workflow"))
    except Exception:
        return False


def apply_exif(img, metadata):
    exif = img.getexif()
    prompt = metadata.get("prompt") or ""
    workflow = metadata.get("workflow") or ""
    if prompt:
        exif[0x010f] = "Prompt: " + prompt
    if workflow:
        exif[0x010e] = "Workflow: " + workflow
    return exif.tobytes()


# -- Conversion --------------------------------------------------------------

def _prepare_image(img, fmt):
    if fmt == "jpeg" and img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        if img.mode in ("RGBA", "LA"):
            bg.paste(img, mask=img.split()[-1])
        else:
            bg.paste(img)
        return bg
    if fmt == "webp" and img.mode == "P":
        return img.convert("RGBA")
    return img


def _build_save_kwargs(img, metadata, fmt, quality, lossless):
    save_kwargs = {"quality": int(quality)}
    if metadata["prompt"] or metadata["workflow"]:
        save_kwargs["exif"] = apply_exif(img, metadata)
    if fmt == "webp":
        save_kwargs["method"] = 6
        if lossless:
            save_kwargs["lossless"] = True
    elif fmt == "jpeg":
        save_kwargs["subsampling"] = 0
        save_kwargs["optimize"] = True
    return save_kwargs


def _date_subdir(src_path, date_sort, multi_year=False, day_style="flat"):
    """Retourne le sous-dossier de date.
    day_style: 'flat' -> MM-DD dossier unique, 'nested' -> MM/DD dossiers imbriqués.
    Si multi_year, préfixe avec YYYY-.
    """
    if date_sort == "none":
        return Path()
    try:
        dt = datetime.fromtimestamp(Path(src_path).stat().st_mtime)
        if date_sort == "month":
            return Path(dt.strftime("%Y-%m") if multi_year else dt.strftime("%m"))
        elif date_sort == "day":
            if day_style == "nested":
                month = dt.strftime("%Y-%m") if multi_year else dt.strftime("%m")
                return Path(month) / dt.strftime("%d")
            else:
                return Path(dt.strftime("%Y-%m-%d") if multi_year else dt.strftime("%m-%d"))
    except Exception:
        pass
    return Path()


def convert_image(src_path, dst_path, fmt="webp", quality=90, lossless=False,
                  strip_workflow=False):
    src_path = Path(src_path)
    dst_path = Path(dst_path)

    try:
        img = Image.open(src_path)
        img.load()
    except Exception as e:
        return False, f"Read failed: {e}", 0

    metadata = extract_comfy_metadata(img)
    has_metadata = bool(metadata["prompt"] or metadata["workflow"])

    if strip_workflow:
        metadata = {"prompt": "", "workflow": ""}

    fmt = "jpeg" if fmt.lower() == "jpg" else fmt.lower()
    img = _prepare_image(img, fmt)
    save_kwargs = _build_save_kwargs(img, metadata, fmt, quality, lossless)

    dst_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        original_size = src_path.stat().st_size
        img.save(dst_path, fmt.upper(), **save_kwargs)
        new_size = dst_path.stat().st_size
        _copy_timestamps(src_path, dst_path)
    except Exception as e:
        return False, f"Ecriture echouee : {e}", 0

    ratio = (1 - new_size / original_size) * 100 if original_size else 0

    if strip_workflow and has_metadata:
        return True, f"OK (-{ratio:.0f}%, workflow stripped)", new_size
    if not has_metadata:
        return True, f"OK (-{ratio:.0f}%, no workflow)", new_size
    if fmt == "webp" and lossless:
        return True, f"OK (-{ratio:.0f}%, lossless not readable by ComfyUI)", new_size
    return True, f"OK (-{ratio:.0f}%)", new_size


def convert_to_bytes(img, fmt, quality, lossless=False):
    fmt = "jpeg" if fmt.lower() == "jpg" else fmt.lower()
    img_prepared = _prepare_image(img, fmt)
    save_kwargs = _build_save_kwargs(
        img_prepared, {"prompt": "", "workflow": ""}, fmt, quality, lossless
    )
    buf = io.BytesIO()
    img_prepared.save(buf, fmt.upper(), **save_kwargs)
    return buf.getvalue()


# -- Estimation taille -------------------------------------------------------

_WEBP_POINTS = [(50, 0.05), (70, 0.08), (80, 0.10), (85, 0.12),
                (90, 0.15), (95, 0.22), (100, 0.30)]
_JPG_POINTS  = [(50, 0.07), (70, 0.11), (80, 0.16), (85, 0.20),
                (90, 0.25), (95, 0.32), (100, 0.45)]


def estimate_factor(fmt, quality, lossless=False):
    if lossless and fmt.lower() == "webp":
        return 0.50
    points = _WEBP_POINTS if fmt.lower() == "webp" else _JPG_POINTS
    quality = max(50, min(100, quality))
    for i in range(len(points) - 1):
        q1, f1 = points[i]
        q2, f2 = points[i + 1]
        if q1 <= quality <= q2:
            return f1 + (f2 - f1) * (quality - q1) / (q2 - q1)
    return points[-1][1]


# -- Iteration sources -------------------------------------------------------

def iter_pngs(source, recursive=False):
    source = Path(source)
    if source.is_file():
        if source.suffix.lower() == ".png":
            yield source
        return
    pattern = "**/*.png" if recursive else "*.png"
    for p in sorted(source.glob(pattern)):
        if p.is_file():
            yield p


def scan_sources(sources, recursive=False):
    if isinstance(sources, (list, tuple)):
        files = [Path(p) for p in sources if Path(p).suffix.lower() == ".png"]
        base = None
    else:
        source = Path(sources)
        files = list(iter_pngs(source, recursive=recursive))
        base = source if source.is_dir() else source.parent

    total_size = sum(f.stat().st_size for f in files if f.exists())
    return files, total_size, base


# -- Conversion en lot -------------------------------------------------------

def batch_convert(
    sources,
    output_dir=None,
    fmt="webp",
    quality=90,
    lossless=False,
    recursive=False,
    preserve_structure=True,
    package_subfolder=None,
    date_sort="none",
    date_day_style="flat",
    date_placement="root",
    strip_workflow=False,
    files_to_copy=None,
    workers=2,
    force_year_prefix=False,
    progress_callback=None,
    stop_event=None,
    no_workflow_files=None,
    copy_callback=None,
):
    """
    sources          : Path (fichier/dossier) ou liste de Path.
    output_dir       : dossier de sortie. None = à côté des sources.
    package_subfolder: crée un sous-dossier de ce nom dans output_dir.
    preserve_structure: recrée l'arborescence des sous-dossiers source.
    date_sort        : "none" | "month" | "day"
    date_day_style   : "flat" (MM-DD) | "nested" (MM/DD)
    date_placement   : "root" (date en tête) | "leaf" (date dans sous-dossiers)
    strip_workflow   : supprime les métadonnées ComfyUI des fichiers de sortie.
    workers          : nombre de threads parallèles pour la conversion.
    """
    files, _, base = scan_sources(sources, recursive=recursive)
    total = len(files)

    if total == 0:
        if progress_callback:
            progress_callback(0, 0, "", "Aucun PNG trouvé.", 0, 0)
        return {"total": 0, "success": 0, "failed": 0, "stopped": False, "saved_bytes": 0}

    if output_dir is not None:
        output_dir = Path(output_dir)
        if package_subfolder:
            safe = "".join(c for c in package_subfolder if c not in r'<>:"/\|?*').strip()
            if safe:
                output_dir = output_dir / safe
        output_dir.mkdir(parents=True, exist_ok=True)

    ext = "webp" if fmt.lower() == "webp" else "jpg"

    multi_year = False
    if date_sort != "none":
        try:
            years = {datetime.fromtimestamp(f.stat().st_mtime).year for f in files if f.exists()}
            multi_year = len(years) > 1
        except Exception:
            pass
        if force_year_prefix:
            multi_year = True

    def _dst(src, effective_out):
        if effective_out is None:
            return src.with_suffix(f".{ext}")
        date_sub = _date_subdir(src, date_sort, multi_year=multi_year, day_style=date_day_style)
        if preserve_structure and base is not None and src.is_relative_to(base):
            rel = src.relative_to(base).with_suffix(f".{ext}")
            rel_dir = rel.parent
            if date_placement == "leaf":
                return effective_out / rel_dir / date_sub / src.with_suffix(f".{ext}").name
            return effective_out / date_sub / rel
        return effective_out / date_sub / src.with_suffix(f".{ext}").name

    _no_wf_set = frozenset(no_workflow_files) if no_workflow_files else frozenset()

    lock = _thd.Lock()
    counter = [0]
    success_c = [0]
    failed_c = [0]
    saved_c = [0]
    stopped_flag = [False]
    times = []

    def _process(src):
        if stop_event is not None and stop_event.is_set():
            stopped_flag[0] = True
            return
        is_no_wf = bool(_no_wf_set and src in _no_wf_set and output_dir is not None)
        if is_no_wf:
            normal_dst = _dst(src, output_dir)
            dst = normal_dst.parent / "no-workflow" / normal_dst.name
        else:
            dst = _dst(src, output_dir)
        t0 = time.time()
        old_size = src.stat().st_size
        ok, msg, new_size = convert_image(
            src, dst, fmt=fmt, quality=quality,
            lossless=lossless, strip_workflow=strip_workflow,
        )
        elapsed = time.time() - t0
        with lock:
            counter[0] += 1
            i = counter[0]
            if ok:
                success_c[0] += 1
                saved_c[0] += old_size - new_size
            else:
                failed_c[0] += 1
            times.append(elapsed)
            if len(times) > 10:
                times.pop(0)
            avg = sum(times) / len(times)
            eta = avg * (total - i)
        if progress_callback:
            progress_callback(i, total, src.name, msg, elapsed, eta, is_no_wf)

    n_workers = max(1, min(workers, total))
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as executor:
        executor.map(_process, files)

    if files_to_copy and output_dir is not None and not stopped_flag[0]:
        for src in files_to_copy:
            date_sub = _date_subdir(src, date_sort, multi_year=multi_year, day_style=date_day_style)
            if preserve_structure and base is not None and src.is_relative_to(base):
                rel = src.relative_to(base)
                if date_placement == "leaf":
                    dst = output_dir / rel.parent / date_sub / rel.name
                else:
                    dst = output_dir / date_sub / rel
            else:
                dst = output_dir / date_sub / src.name
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                if copy_callback:
                    copy_callback(src, dst, True)
            except Exception:
                if copy_callback:
                    copy_callback(src, dst, False)

    return {
        "total": total,
        "success": success_c[0],
        "failed": failed_c[0],
        "stopped": stopped_flag[0],
        "saved_bytes": saved_c[0],
    }


# -- Aperçu côte à côte ------------------------------------------------------

def render_preview_pair(src_path, fmt, quality, lossless=False, view_size=400, zoom=1):
    src_path = Path(src_path)
    img = Image.open(src_path)
    img.load()

    converted_bytes = convert_to_bytes(img, fmt, quality, lossless=lossless)
    converted = Image.open(io.BytesIO(converted_bytes))
    converted.load()

    crop_native = max(1, view_size // zoom)
    cx, cy = img.width // 2, img.height // 2
    half = crop_native // 2
    box = (cx - half, cy - half, cx + half, cy + half)
    box = (max(0, box[0]), max(0, box[1]),
           min(img.width, box[2]), min(img.height, box[3]))

    orig_crop = img.crop(box)
    conv_crop = converted.crop(box)

    if zoom > 1:
        orig_crop = orig_crop.resize((view_size, view_size), Image.NEAREST)
        conv_crop = conv_crop.resize((view_size, view_size), Image.NEAREST)
    else:
        if orig_crop.size != (view_size, view_size):
            orig_crop = orig_crop.resize((view_size, view_size), Image.LANCZOS)
            conv_crop = conv_crop.resize((view_size, view_size), Image.LANCZOS)

    return orig_crop, conv_crop, src_path.stat().st_size, len(converted_bytes)

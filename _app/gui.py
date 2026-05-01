"""
ShrinkComfy - Interface style Windows 11 Settings.
Sans header (titre dans la titlebar suffit), suit le theme systeme.
"""

import sys
from io import BytesIO
from pathlib import Path
import random
from datetime import datetime
from collections import Counter

# DPI awareness AVANT tkinter
if sys.platform == "win32":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import tkinter.font as tkfont
import threading
import queue

# ── Splash screen (visible while heavy deps load) ─────────────────────────────
_splash = tk.Tk()
_splash.overrideredirect(True)
_splash.configure(bg="#1c1c1c")
_W, _H = 260, 68
_splash.geometry(
    f"{_W}x{_H}"
    f"+{(_splash.winfo_screenwidth()  - _W) // 2}"
    f"+{(_splash.winfo_screenheight() - _H) // 2}"
)
_splash.attributes("-topmost", True)
tk.Label(_splash, text="ShrinkComfy", fg="#e8e8e8", bg="#1c1c1c",
         font=("Segoe UI", 14, "bold")).pack(pady=(14, 2))
tk.Label(_splash, text="Loading…",   fg="#555555", bg="#1c1c1c",
         font=("Segoe UI", 9)).pack()
_splash.update()
# ──────────────────────────────────────────────────────────────────────────────

from PIL import Image, ImageDraw, ImageOps, ImageTk

from convert import batch_convert, scan_sources, estimate_factor, convert_to_bytes
from hierarchy import build_hierarchy_lines, build_file_tree_text, HierarchyParams
from theme import detect_system_theme, palette, apply_theme
from utils import human_size


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
DEFAULT_OUTPUT = ROOT_DIR / "output"

# Extensions image non-PNG considérées comme "non prises en charge"
_UNSUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".webp", ".gif", ".tiff", ".tif",
    ".bmp", ".heic", ".heif", ".avif", ".psd", ".cr2",
    ".raw", ".nef", ".dng", ".arw", ".orf",
}



ICON_DIR = APP_DIR / "icons"



def _fit_icon(img, size):
    img = ImageOps.contain(img, (size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    canvas.alpha_composite(img, (x, y))
    return canvas


def _load_icon(key, size=34):
    png_path = ICON_DIR / f"{key}.png"
    if png_path.exists():
        try:
            return _fit_icon(Image.open(png_path).convert("RGBA"), size)
        except Exception:
            pass
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        (5, 5, size - 5, size - 5), radius=6, fill="#8a8a8a"
    )
    return img


def build_sidebar_icons():
    return {
        key: ImageTk.PhotoImage(_load_icon(key))
        for key in ("source", "output", "settings", "preview", "convert")
    }


def detect_fonts():
    families = set(tkfont.families())
    text = ("Segoe UI Variable Text" if "Segoe UI Variable Text" in families
            else "Segoe UI Variable" if "Segoe UI Variable" in families
            else "Segoe UI")
    display = ("Segoe UI Variable Display" if "Segoe UI Variable Display" in families
               else "Segoe UI Variable" if "Segoe UI Variable" in families
               else "Segoe UI")
    emoji = "Segoe UI Emoji" if "Segoe UI Emoji" in families else "Segoe UI Symbol"
    return text, display, emoji


# -- Widgets utilitaires -----------------------------------------------------

class SidebarItem(tk.Canvas):
    def __init__(self, parent, icon, label, command, app):
        self.app = app
        self.pal = app.pal
        super().__init__(
            parent, height=56, bg=self.pal["sidebar_bg"], cursor="hand2",
            highlightthickness=0, bd=0,
        )
        self.icon = icon
        self.label = label
        self._command = command
        self._selected = False
        self._hover = False

        self.bind("<Configure>", lambda _: self._paint())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        self.create_arc(x1, y1, x1 + r * 2, y1 + r * 2, start=90, extent=90, **kw)
        self.create_arc(x2 - r * 2, y1, x2, y1 + r * 2, start=0, extent=90, **kw)
        self.create_arc(x2 - r * 2, y2 - r * 2, x2, y2, start=270, extent=90, **kw)
        self.create_arc(x1, y2 - r * 2, x1 + r * 2, y2, start=180, extent=90, **kw)
        self.create_rectangle(x1 + r, y1, x2 - r, y2, **kw)
        self.create_rectangle(x1, y1 + r, x2, y2 - r, **kw)

    def _paint(self):
        self.delete("all")
        w = max(self.winfo_width(), 1)
        if self._selected:
            fill = self.pal["accent_subtle"]
            text = self.pal["accent_text"]
            font = (self.app.font_text, 10, "bold")
        elif self._hover:
            fill = self.pal["sidebar_hover"]
            text = self.pal["text"]
            font = (self.app.font_text, 10)
        else:
            fill = self.pal["sidebar_bg"]
            text = self.pal["text"]
            font = (self.app.font_text, 10)

        self._rounded_rect(7, 5, w - 7, 51, 8, fill=fill, outline="", width=0)
        self.create_image(25, 28, image=self.icon)
        self.create_text(54, 28, text=self.label, anchor="w", fill=text, font=font)

    def _on_enter(self, _):
        self._hover = True
        self._paint()

    def _on_leave(self, _):
        self._hover = False
        self._paint()

    def _on_click(self, _):
        if self._command:
            self._command()

    def select(self, on):
        self._selected = on
        self._paint()


class Card(tk.Frame):
    """Surface elevee style Win11 : bordure subtile, padding interne."""
    def __init__(self, parent, app, **kw):
        self.pal = app.pal
        super().__init__(
            parent, bg=self.pal["surface"],
            highlightbackground=self.pal["border"], highlightthickness=1, bd=0, **kw,
        )

    def content(self, padx=24, pady=18):
        f = tk.Frame(self, bg=self.pal["surface"])
        f.pack(fill="both", expand=True, padx=padx, pady=pady)
        return f


class FancyProgressBar(tk.Canvas):
    """Progress bar with gradient fill and shimmer animation."""
    _H = 14

    def __init__(self, parent, app, **kw):
        super().__init__(parent, height=self._H, bd=0, highlightthickness=0,
                         bg=app.pal["surface"], **kw)
        self._app = app
        self._val = 0
        self._max = 100
        self._photo = None
        self._shimmer = 0
        self._anim_id = None
        self.bind("<Configure>", lambda _e: self.after_idle(self._draw))

    def configure(self, **kw):
        changed = False
        if "value" in kw:
            self._val = int(kw.pop("value"))
            changed = True
        if "maximum" in kw:
            self._max = int(kw.pop("maximum"))
            changed = True
        if kw:
            super().configure(**kw)
        if changed:
            self._draw()

    def start_anim(self):
        if self._anim_id is None:
            self._tick()

    def stop_anim(self):
        if self._anim_id:
            try:
                self.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None
        self._shimmer = 0

    def _tick(self):
        w = max(1, self.winfo_width())
        self._shimmer = (self._shimmer + 5) % (w + 120)
        self._draw()
        self._anim_id = self.after(20, self._tick)

    def _hex_rgb(self, h):
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def _draw(self):
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1:
            return
        dark = self._app.theme_mode == "dark"
        surf = self._hex_rgb(self._app.pal["surface"])
        track = (55, 55, 55, 255) if dark else (218, 218, 218, 255)

        base = Image.new("RGBA", (w, h), (*surf, 255))
        track_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        r = h // 2
        try:
            ImageDraw.Draw(track_layer).rounded_rectangle(
                [0, 0, w - 1, h - 1], radius=r, fill=track)
        except AttributeError:
            ImageDraw.Draw(track_layer).rectangle([0, 0, w - 1, h - 1], fill=track)
        base = Image.alpha_composite(base, track_layer)

        fill_w = min(w, max(0, round(w * self._val / max(1, self._max))))
        if fill_w > 0:
            if dark:
                c1, c2 = (28, 95, 185, 255), (76, 194, 255, 255)
            else:
                c1, c2 = (0, 75, 160, 255), (24, 130, 220, 255)
            fill_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            fd = ImageDraw.Draw(fill_layer)
            segs = min(fill_w, 40)
            for s in range(segs):
                x1 = fill_w * s // segs
                x2 = fill_w * (s + 1) // segs
                t = s / max(1, segs - 1)
                c = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(4))
                fd.rectangle([x1, 0, x2, h], fill=c)
            # Rounded mask for fill
            fill_mask = Image.new("L", (w, h), 0)
            try:
                ImageDraw.Draw(fill_mask).rounded_rectangle(
                    [0, 0, fill_w - 1, h - 1], radius=r, fill=255)
            except AttributeError:
                ImageDraw.Draw(fill_mask).rectangle([0, 0, fill_w - 1, h - 1], fill=255)
            # Also clip to overall bar
            bar_mask = Image.new("L", (w, h), 0)
            try:
                ImageDraw.Draw(bar_mask).rounded_rectangle(
                    [0, 0, w - 1, h - 1], radius=r, fill=255)
            except AttributeError:
                ImageDraw.Draw(bar_mask).rectangle([0, 0, w - 1, h - 1], fill=255)
            from PIL import ImageChops
            combined = ImageChops.darker(fill_mask, bar_mask)
            fill_layer.putalpha(combined)
            # Shimmer overlay
            if self._anim_id is not None and self._shimmer > 0:
                shimmer_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                sw = 90
                sd = ImageDraw.Draw(shimmer_layer)
                for px in range(max(0, self._shimmer - sw), min(fill_w, self._shimmer)):
                    dist = (self._shimmer - px) / sw
                    alpha = int((1 - dist) ** 1.5 * 70)
                    sd.line([(px, 0), (px, h)], fill=(255, 255, 255, alpha))
                shimmer_layer.putalpha(combined)
                fill_layer = Image.alpha_composite(fill_layer, shimmer_layer)
            base = Image.alpha_composite(base, fill_layer)

        self._photo = ImageTk.PhotoImage(base.convert("RGB"))
        self.delete("all")
        self.create_image(0, 0, image=self._photo, anchor="nw")


# -- Application principale --------------------------------------------------

# TODO: découper ConverterApp en classes de pages séparées (SourcePage, OutputPage,
#       SettingsPage, PreviewPage, ConvertPage). Chaque page recevra une référence à
#       l'app pour accéder à l'état partagé (self.app.scanned_files, etc.).
#       hierarchy.py et utils.py sont déjà extraits — c'est la prochaine étape.
class ConverterApp:
    PAGES = [
        ("source",   "Source"),
        ("output",   "Output"),
        ("settings", "Settings"),
        ("preview",  "Preview"),
        ("convert",  "Convert"),
    ]

    def __init__(self, root):
        self.root = root
        self.font_text, self.font_display, self.font_emoji = detect_fonts()

        self.theme_mode = detect_system_theme()
        self.pal = apply_theme(root, self.theme_mode)
        self.sidebar_icons = build_sidebar_icons()

        root.title("ShrinkComfy")
        self._apply_app_icon()
        root.geometry("1000x700")
        root.minsize(860, 620)
        root.configure(bg=self.pal["bg"])

        # Etat source
        self.source_paths = []
        self.source_is_folder = False
        self.scanned_files = []
        self.scanned_total_bytes = 0
        self._source_scan_counter = 0

        # Variables output / settings
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.format_var = tk.StringVar(value="webp")
        self.quality_var = tk.IntVar(value=90)
        self.recursive_var = tk.BooleanVar(value=True)
        self.lossless_var = tk.BooleanVar(value=False)
        self.same_dir_var = tk.BooleanVar(value=False)
        self.preserve_var = tk.BooleanVar(value=True)
        self.package_var = tk.BooleanVar(value=True)
        self.package_name_var = tk.StringVar(value=f"SHRINK-{datetime.now().strftime('%Y-%m-%d')}")
        self.date_sort_var = tk.StringVar(value="none")
        self.date_placement_var = tk.StringVar(value="root")
        self.date_day_style_var = tk.StringVar(value="flat")
        self.date_force_year_var = tk.BooleanVar(value=False)
        self.dest_mode_var = tk.StringVar(value="default")
        self.package_mode_var = tk.StringVar(value="custom")
        self.workers_var = tk.IntVar(value=2)
        self.strip_workflow_var = tk.BooleanVar(value=False)
        self.strip_workflow_confirm_var = tk.BooleanVar(value=False)
        self.copy_unsupported_var = tk.BooleanVar(value=False)
        self._unsupported_files = []
        self.sort_no_workflow_var = tk.BooleanVar(value=False)
        self._files_without_workflow = []
        self._last_output_dir = None

        # Backing store pour le chemin de sortie quand same_dir est actif
        self._manual_output = str(DEFAULT_OUTPUT)
        self._source_display_showing = False

        # Preview
        self.preview_image_path = None
        self.preview_mode = tk.StringVar(value="side")
        self.preview_zoom = tk.DoubleVar(value=2.0)
        self._preview_photo_left = None
        self._preview_photo_right = None
        self._preview_photo_slider = None
        self._preview_original_full = None
        self._preview_converted_full = None
        self._preview_original_bytes = 0
        self._preview_converted_bytes = 0
        self._preview_pan = (0.5, 0.5)
        self._preview_split = 0.5
        self._slider_dragging = False
        self._preview_refresh_after = None
        self._preview_pending = False

        # Workflow metadata stats
        self._workflow_check_counter = 0
        self._total_workflow_bytes = 0
        self._workflow_file_count = 0

        self.log_queue = queue.Queue()
        self.is_running = False
        self.stop_event = threading.Event()

        self.pages = {}
        self.sidebar_items = {}
        self.current_page = None

        self._configure_ttk()
        self._build_layout()
        self._build_all_pages()
        self._goto_page("source")
        self._poll_log_queue()
        self._refresh_stats()

    def _apply_app_icon(self):
        try:
            self.root.iconbitmap(str(ICON_DIR / "app.ico"))
        except Exception:
            pass

    def _configure_ttk(self):
        style = ttk.Style()
        FT = (self.font_text, 10)

        style.configure("TFrame", background=self.pal["bg"])

        # sv_ttk applies theme BEFORE this; our overrides follow.
        for w in ("TCheckbutton", "TRadiobutton"):
            style.configure(w, background=self.pal["surface"], font=FT)
            style.map(w, background=[
                ("active",   self.pal["surface"]),
                ("disabled", self.pal["surface"]),
                ("pressed",  self.pal["surface"]),
            ])
        style.configure("TScale", background=self.pal["surface"])
        style.map("TScale", background=[("active", self.pal["surface"])])

        style.configure("TButton", font=FT, padding=(10, 5))
        style.configure("Accent.TButton", font=FT, padding=(14, 7))
        style.configure("TEntry", font=FT)

        style.configure("Vertical.TScrollbar", background=self.pal["bg"])

        try:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
                f = tkfont.nametofont(name)
                f.config(family=self.font_text, size=10)
        except Exception:
            pass

        style.configure("Win11.TButton",
                        padding=(14, 7),
                        font=FT)
        style.map("Win11.TButton",
                  background=[
                      ("active",  self.pal["border_strong"]),
                      ("pressed", self.pal["sidebar_sel"]),
                  ])

    # -- Layout principal --------------------------------------------------

    def _build_layout(self):
        tk.Frame(self.root, bg=self.pal["border"], height=1).pack(fill="x")
        body = tk.Frame(self.root, bg=self.pal["bg"])
        body.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(body, bg=self.pal["sidebar_bg"], width=230)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        tk.Frame(self.sidebar, bg=self.pal["sidebar_bg"], height=18).pack(fill="x")

        for key, label in self.PAGES:
            item = SidebarItem(self.sidebar, self.sidebar_icons[key], label,
                               lambda k=key: self._goto_page(k), self)
            item.pack(fill="x", padx=8, pady=3)
            self.sidebar_items[key] = item

        footer = tk.Frame(self.sidebar, bg=self.pal["sidebar_bg"])
        footer.pack(side="bottom", fill="x", padx=18, pady=18)
        tk.Label(footer, text="SOURCE DETECTED", bg=self.pal["sidebar_bg"],
                 fg=self.pal["text_muted"], font=(self.font_text, 10, "bold"),
                 anchor="w").pack(fill="x")
        self.sidebar_count = tk.Label(
            footer, text="—", bg=self.pal["sidebar_bg"], fg=self.pal["text"],
            font=(self.font_text, 10), anchor="w", justify="left",
        )
        self.sidebar_count.pack(fill="x", pady=(2, 0))

        tk.Frame(body, bg=self.pal["border"], width=1).pack(side="left", fill="y")

        self.content_container = tk.Frame(body, bg=self.pal["bg"])
        self.content_container.pack(side="left", fill="both", expand=True)

    def _build_all_pages(self):
        for key, _ in self.PAGES:
            f = tk.Frame(self.content_container, bg=self.pal["bg"])
            self.pages[key] = f
        self._build_page_source()
        self._build_page_output()
        self._build_page_settings()
        self._build_page_preview()
        self._build_page_convert()

    def _goto_page(self, key):
        for k, frame in self.pages.items():
            frame.pack_forget()
        for k, item in self.sidebar_items.items():
            item.select(k == key)
        self.pages[key].pack(fill="both", expand=True, padx=32, pady=24)
        self.current_page = key
        if key == "output":
            self._refresh_hierarchy()

    # -- Helpers UI --------------------------------------------------------

    def _section_label(self, parent, text):
        tk.Label(parent, text=text, bg=self.pal["surface"], fg=self.pal["text"],
                 font=(self.font_text, 11, "bold")).pack(anchor="w", pady=(0, 8))

    def _hint(self, parent, text, **kw):
        return tk.Label(parent, text=text, bg=self.pal["surface"],
                        fg=self.pal["text_secondary"], font=(self.font_text, 10),
                        anchor="w", justify="left", wraplength=580, **kw)

    def _scrollable_page(self, outer):
        """Retourne un frame scrollable pour remplir outer.
        La barre de défilement est masquée quand tout le contenu tient à l'écran.
        Le scroll molette est ignoré sur les widgets Text (journaux internes)."""
        _sc = tk.Canvas(outer, bg=self.pal["bg"], highlightthickness=0, bd=0)
        _sb = ttk.Scrollbar(outer, orient="vertical", command=_sc.yview)
        _sc.pack(side="left", fill="both", expand=True)

        def _on_scroll(first, last):
            if float(first) <= 0.0 and float(last) >= 1.0:
                _sb.pack_forget()
            else:
                _sb.pack(side="right", fill="y", padx=(8, 0), before=_sc)
            _sb.set(first, last)

        _sc.configure(yscrollcommand=_on_scroll)
        p = tk.Frame(_sc, bg=self.pal["bg"])
        _win = _sc.create_window((0, 0), window=p, anchor="nw")

        def _update_scrollregion(_e=None):
            _sc.configure(scrollregion=(0, 0, p.winfo_reqwidth(), p.winfo_reqheight()))

        p.bind("<Configure>", _update_scrollregion)
        _sc.bind("<Configure>", lambda e: _sc.itemconfig(_win, width=e.width))

        def _wheel(e):
            if e.widget.winfo_class() == "Text":
                return
            first, last = _sc.yview()
            # Nothing to scroll
            if first <= 0.0 and last >= 1.0:
                return
            # Already at top — block upward scroll
            if e.delta > 0 and first <= 0.0:
                return
            _sc.yview_scroll(-1 * (e.delta // 120), "units")

        _sc.bind("<Enter>", lambda _e: _sc.bind_all("<MouseWheel>", _wheel))
        _sc.bind("<Leave>", lambda _e: _sc.unbind_all("<MouseWheel>"))

        # Reset to top each time this page becomes visible (page switch)
        outer.bind("<Map>", lambda e: _sc.yview_moveto(0) if e.widget is outer else None)
        return p

    # -- Page 1 : Source ---------------------------------------------------

    def _build_page_source(self):
        p = self._scrollable_page(self.pages["source"])

        card = Card(p, self); card.pack(fill="x", pady=(0, 24))
        c = card.content()
        self._section_label(c, "What do you want to convert?")

        btn_row = tk.Frame(c, bg=self.pal["surface"]); btn_row.pack(fill="x", pady=(0, 8))
        ttk.Button(btn_row, text="Choose folder...", style="Win11.TButton",
                   command=self._pick_folder).pack(side="left", padx=(0, 14))
        ttk.Button(btn_row, text="Choose images...", style="Win11.TButton",
                   command=self._pick_files).pack(side="left")

        self.recursive_check = ttk.Checkbutton(
            c, text="Include subfolders", variable=self.recursive_var,
            command=self._on_source_changed,
        )
        self.recursive_check.pack(anchor="w", pady=(0, 10))
        self.recursive_check.state(["disabled"])

        self.source_summary = tk.Label(
            c, text="No source selected.", bg=self.pal["surface"],
            fg=self.pal["text_secondary"], font=(self.font_text, 10),
            anchor="w", justify="left", wraplength=580,
        )
        self.source_summary.pack(fill="x", pady=(2, 2))

        # Avertissement fichiers non pris en charge (dossier uniquement)
        self.source_unsupported_label = tk.Label(
            c, text="", bg=self.pal["surface"],
            fg=self.pal["text_secondary"], font=(self.font_text, 10),
            anchor="w", justify="left", wraplength=580,
        )
        self.source_unsupported_label.pack(fill="x", pady=(0, 2))

        self.copy_unsupported_check = ttk.Checkbutton(
            c,
            text="Copy non-convertible files to output folder as-is",
            variable=self.copy_unsupported_var,
        )
        self.copy_unsupported_check.pack(anchor="w", padx=(16, 0), pady=(0, 4))
        self.copy_unsupported_check.pack_forget()

        # Badge workflow ComfyUI
        self.source_workflow_badge = tk.Label(
            c, text="", bg=self.pal["surface"],
            font=(self.font_text, 10, "bold"), anchor="w",
        )
        self.source_workflow_badge.pack(fill="x", pady=(0, 4))

        # Journal des images sans workflow (masqué par défaut)
        self._source_log_frame = tk.Frame(c, bg=self.pal["surface"])
        tk.Label(
            self._source_log_frame, text="Images without ComfyUI workflow:",
            bg=self.pal["surface"], fg=self.pal["text_muted"], font=(self.font_text, 10),
        ).pack(anchor="w", pady=(2, 2))
        self.source_log = tk.Text(
            self._source_log_frame, height=4, wrap="word", font=("Consolas", 10),
            bg=self.pal["log_bg"], fg=self.pal["text"], relief="flat", bd=0,
            highlightthickness=1, highlightbackground=self.pal["border"],
            padx=8, pady=6,
        )
        self.source_log.pack(fill="x")
        self.source_log.configure(state="disabled")
        self._source_log_frame.pack(fill="x", pady=(0, 4))
        self._source_log_frame.pack_forget()

        # Journal des fichiers non pris en charge (masqué par défaut)
        self._source_unsupported_log_frame = tk.Frame(c, bg=self.pal["surface"])
        tk.Label(
            self._source_unsupported_log_frame, text="Non-convertible files found:",
            bg=self.pal["surface"], fg=self.pal["text_muted"], font=(self.font_text, 10),
        ).pack(anchor="w", pady=(2, 2))
        self.source_unsupported_log = tk.Text(
            self._source_unsupported_log_frame, height=4, wrap="word",
            font=("Consolas", 10),
            bg=self.pal["log_bg"], fg=self.pal["text"], relief="flat", bd=0,
            highlightthickness=1, highlightbackground=self.pal["border"],
            padx=8, pady=6,
        )
        self.source_unsupported_log.pack(fill="x")
        self.source_unsupported_log.configure(state="disabled")
        self._source_unsupported_log_frame.pack(fill="x", pady=(0, 4))
        self._source_unsupported_log_frame.pack_forget()


    def _pick_folder(self):
        path = filedialog.askdirectory(title="Select a folder")
        if path:
            self.source_paths = [Path(path)]
            self.source_is_folder = True
            self._on_source_changed()

    def _pick_files(self):
        files = filedialog.askopenfilenames(
            title="Select one or more PNG images",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")],
        )
        if files:
            self.source_paths = [Path(f) for f in files]
            self.source_is_folder = False
            self._on_source_changed()

    def _on_source_changed(self):
        self._update_source_controls()
        if self.dest_mode_var.get() == "same":
            self.output_var.set(self._get_source_display_path())
        self._update_source_summary()

    def _update_source_summary(self):
        if not self.source_paths:
            self.scanned_files = []
            self.scanned_total_bytes = 0
            self.source_summary.config(text="No source selected.",
                                       fg=self.pal["text_secondary"])
            self.source_unsupported_label.config(text="")
            self.sidebar_count.config(text="—")
            self.source_workflow_badge.config(text="")
            self._source_log_frame.pack_forget()
            self._refresh_stats()
            return

        # Show immediate feedback while the background scan runs
        self.source_summary.config(text="Scanning…", fg=self.pal["text_muted"])
        self.sidebar_count.config(text="…")
        self.source_workflow_badge.config(text="")
        self._source_log_frame.pack_forget()

        self._source_scan_counter += 1
        counter = self._source_scan_counter
        sources = self.source_paths[0] if self.source_is_folder else list(self.source_paths)
        is_folder = self.source_is_folder
        folder = self.source_paths[0] if is_folder else None
        recursive = self.recursive_var.get()

        threading.Thread(
            target=self._scan_source_worker,
            args=(sources, is_folder, folder, recursive, counter),
            daemon=True,
        ).start()

    def _scan_source_worker(self, sources, is_folder, folder, recursive, counter):
        try:
            files, total, _ = scan_sources(sources, recursive=recursive)
        except Exception as e:
            self.root.after(0, lambda: self.source_summary.config(
                text=f"Error: {e}", fg=self.pal["danger"]))
            return

        unsupported_files = []
        ext_counts = Counter()
        if is_folder and folder:
            pattern = "**/*" if recursive else "*"
            scanned = 0
            try:
                for p in folder.glob(pattern):
                    if scanned >= 20000:
                        break
                    scanned += 1
                    if p.is_file() and p.suffix.lower() != ".png":
                        ext_counts[p.suffix.lower()] += 1
                        unsupported_files.append(p)
            except Exception:
                pass

        self.root.after(0, lambda: self._apply_scan_results(
            files, total, is_folder, folder, ext_counts, unsupported_files, counter
        ))

    def _apply_scan_results(self, files, total, is_folder, folder,
                            ext_counts, unsupported_files, counter):
        if self._source_scan_counter != counter:
            return

        self.scanned_files = files
        self.scanned_total_bytes = total
        self._unsupported_files = unsupported_files
        self._files_without_workflow = []  # reset until workflow check completes

        if is_folder and folder:
            txt = f"Folder: {folder.name}\n{len(files)} PNG image(s) · {human_size(total)}"
        elif len(files) == 1:
            txt = f"File: {files[0].name}\n{human_size(total)}"
        else:
            txt = f"{len(files)} files selected\n{human_size(total)}"

        self.source_summary.config(text=txt, fg=self.pal["text"])
        self.sidebar_count.config(text=f"{len(files)} file(s)\n{human_size(total)}")

        if ext_counts:
            parts = [f"{count} {ext}" for ext, count in sorted(ext_counts.items())]
            msg = "ℹ  Also found: " + ", ".join(parts) + " (not converted, PNG only)"
            self.source_unsupported_label.config(text=msg, fg=self.pal["text_secondary"])
            self.copy_unsupported_check.pack(
                anchor="w", padx=(16, 0), pady=(0, 4),
                after=self.source_unsupported_label,
            )
            tree_text = self._build_file_tree_text(unsupported_files)
            self.source_unsupported_log.configure(state="normal")
            self.source_unsupported_log.delete("1.0", "end")
            self.source_unsupported_log.insert("end", tree_text)
            line_count = int(self.source_unsupported_log.index("end-1c").split(".")[0])
            self.source_unsupported_log.configure(height=max(3, line_count))
            self.source_unsupported_log.configure(state="disabled")
            self._source_unsupported_log_frame.pack(
                fill="x", pady=(0, 4), after=self.copy_unsupported_check
            )
        else:
            self.copy_unsupported_var.set(False)
            self.source_unsupported_label.config(text="")
            self.copy_unsupported_check.pack_forget()
            self._source_unsupported_log_frame.pack_forget()

        if files:
            check_files = list(files)
            self.source_workflow_badge.config(
                text="Checking ComfyUI workflows…", fg=self.pal["text_muted"]
            )
            self._source_log_frame.pack_forget()
            self._workflow_check_counter += 1
            wf_counter = self._workflow_check_counter
            threading.Thread(
                target=self._check_workflow_metadata,
                args=(check_files, wf_counter),
                daemon=True,
            ).start()
        else:
            self.source_workflow_badge.config(text="")
            self._source_log_frame.pack_forget()

        self._refresh_stats()
        if hasattr(self, "preview_path_label"):
            self._pick_random_preview(auto=True)

    def _check_workflow_metadata(self, files, counter):
        """Thread worker : analyse les métadonnées ComfyUI de chaque image."""
        with_meta = []
        without_meta = []
        total_workflow_bytes = 0
        for f in files:
            try:
                img = Image.open(f)
                wf = img.info.get("workflow") or ""
                pr = img.info.get("prompt") or ""
                if wf or pr:
                    with_meta.append(f)
                    total_workflow_bytes += len(wf.encode("utf-8")) + len(pr.encode("utf-8"))
                else:
                    without_meta.append(f)
            except Exception:
                without_meta.append(f)
        if self._workflow_check_counter == counter:
            self.root.after(0, lambda: self._apply_workflow_badge(
                with_meta, without_meta, total_workflow_bytes, counter
            ))

    def _apply_workflow_badge(self, with_meta, without_meta, workflow_bytes, counter):
        if self._workflow_check_counter != counter:
            return
        self._files_without_workflow = without_meta
        total = len(with_meta) + len(without_meta)
        if total == 0:
            self.source_workflow_badge.config(text="")
            self._source_log_frame.pack_forget()
            return

        if len(without_meta) == 0:
            color = "#22c55e"
            text = f"✓  All {total} images have a ComfyUI workflow"
        elif len(with_meta) == 0:
            color = "#ef4444"
            text = f"✗  None of the {total} images have a ComfyUI workflow"
        else:
            color = "#f59e0b"
            text = (f"⚠  {len(with_meta)} of {total} images have a ComfyUI workflow"
                    f"  ({len(without_meta)} missing)")

        self.source_workflow_badge.config(text=text, fg=color)

        self._total_workflow_bytes = workflow_bytes
        self._workflow_file_count = len(with_meta)
        self._update_strip_info()

        if without_meta:
            tree_text = self._build_file_tree_text(without_meta)
            self.source_log.configure(state="normal")
            self.source_log.delete("1.0", "end")
            self.source_log.insert("end", tree_text)
            line_count = int(self.source_log.index("end-1c").split(".")[0])
            self.source_log.configure(height=max(4, line_count))
            self.source_log.configure(state="disabled")
            self._source_log_frame.pack(
                fill="x", pady=(0, 4), after=self.source_workflow_badge
            )
        else:
            self._source_log_frame.pack_forget()

    def _update_source_controls(self):
        if self.source_is_folder:
            self.recursive_check.state(["!disabled"])
        else:
            self.recursive_check.state(["disabled"])

        if hasattr(self, "preserve_check"):
            if self.dest_mode_var.get() == "same":
                self.preserve_check.state(["disabled"])
            elif self.source_is_folder and self.recursive_var.get():
                self.preserve_check.state(["!disabled"])
            else:
                self.preserve_check.state(["disabled"])

    # -- Page 2 : Sortie ---------------------------------------------------

    def _build_page_output(self):
        p = self._scrollable_page(self.pages["output"])

        # -- Destination -------------------------------------------------------
        card = Card(p, self); card.pack(fill="x", pady=(0, 14))
        c = card.content()
        self._section_label(c, "Destination")

        dest_opts = [
            ("same",    "Next to source files"),
            ("default", f"Default output folder  ({DEFAULT_OUTPUT.name}/)"),
            ("custom",  "Custom path…"),
        ]
        for val, label in dest_opts:
            ttk.Radiobutton(
                c, text=label, variable=self.dest_mode_var, value=val,
                command=self._toggle_dest_mode,
            ).pack(anchor="w", pady=2)

        # Custom path row (shown only for dest_mode == "custom")
        self._custom_path_row = tk.Frame(c, bg=self.pal["surface"])
        self.output_entry = ttk.Entry(
            self._custom_path_row, textvariable=self.output_var)
        self.output_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.output_browse_btn = ttk.Button(
            self._custom_path_row, text="Browse…", style="Win11.TButton",
            command=self._pick_output,
        )
        self.output_browse_btn.pack(side="left", padx=(12, 0))

        # -- Grouping ----------------------------------------------------------
        card = Card(p, self); card.pack(fill="x", pady=(0, 14))
        c = card.content()
        self._section_label(c, "Grouping")

        ttk.Checkbutton(
            c, text="Group output in a subfolder",
            variable=self.package_var, command=self._toggle_package,
        ).pack(anchor="w", pady=(0, 6))

        self._package_sub = tk.Frame(c, bg=self.pal["surface"])
        ttk.Radiobutton(
            self._package_sub, text='Named automatically (source folder / “converted”)',
            variable=self.package_mode_var, value="auto",
            command=self._toggle_package_mode,
        ).pack(anchor="w", padx=(20, 0))
        custom_name_row = tk.Frame(self._package_sub, bg=self.pal["surface"])
        custom_name_row.pack(anchor="w", padx=(20, 0), pady=(4, 0))
        ttk.Radiobutton(
            custom_name_row, text="Custom name:",
            variable=self.package_mode_var, value="custom",
            command=self._toggle_package_mode,
        ).pack(side="left")
        self.package_entry = ttk.Entry(
            custom_name_row, textvariable=self.package_name_var, width=24)
        self.package_entry.pack(side="left", padx=(8, 0), ipady=2)

        self.preserve_check = ttk.Checkbutton(
            c, text="Preserve subfolder structure",
            variable=self.preserve_var,
        )
        self.preserve_check.pack(anchor="w", pady=(8, 0))

        self._toggle_package()
        self._update_source_controls()

        # -- Sort by date ------------------------------------------------------
        card = Card(p, self); card.pack(fill="x", pady=(0, 14))
        c = card.content()
        self._section_label(c, "Sort by date")
        self._hint(c, "Creates date subfolders based on each file's last-modified date."
                   ).pack(anchor="w", pady=(0, 8))

        for lab, val in [
            ("No date sorting", "none"),
            ("By month",        "month"),
            ("By day",          "day"),
        ]:
            ttk.Radiobutton(
                c, text=lab, variable=self.date_sort_var, value=val,
                command=self._toggle_date_sort_options,
            ).pack(anchor="w", pady=2)

        # Sub-options (placement + day style), initially hidden
        self._date_sub_frame = tk.Frame(c, bg=self.pal["surface"])

        tk.Label(self._date_sub_frame, text="Date position:",
                 bg=self.pal["surface"], fg=self.pal["text_secondary"],
                 font=(self.font_text, 10, "bold")).pack(anchor="w", padx=(20, 0), pady=(8, 2))
        for lab, val in [
            ("Date at root: date / subfolders / file", "root"),
            ("Date within subfolders: subfolder / date / file", "leaf"),
        ]:
            ttk.Radiobutton(
                self._date_sub_frame, text=lab,
                variable=self.date_placement_var, value=val,
            ).pack(anchor="w", padx=(28, 0), pady=1)

        self._date_month_frame = tk.Frame(self._date_sub_frame, bg=self.pal["surface"])
        ttk.Checkbutton(
            self._date_month_frame,
            text="Force year prefix: YYYY-MM instead of MM",
            variable=self.date_force_year_var,
        ).pack(anchor="w", padx=(28, 0), pady=(8, 0))
        self._date_month_frame.pack(fill="x")  # inside _date_sub_frame

        self._date_day_frame = tk.Frame(self._date_sub_frame, bg=self.pal["surface"])
        tk.Label(self._date_day_frame, text="Day folder style:",
                 bg=self.pal["surface"], fg=self.pal["text_secondary"],
                 font=(self.font_text, 10, "bold")).pack(anchor="w", padx=(20, 0), pady=(8, 2))
        for lab, val in [
            ("Single folder: 06-15",  "flat"),
            ("Nested: 06 / 15",       "nested"),
        ]:
            ttk.Radiobutton(
                self._date_day_frame, text=lab,
                variable=self.date_day_style_var, value=val,
            ).pack(anchor="w", padx=(28, 0), pady=1)
        self._date_day_frame.pack(fill="x")  # always inside _date_sub_frame

        # -- No-workflow isolation ---------------------------------------------
        card = Card(p, self); card.pack(fill="x", pady=(0, 14))
        c = card.content()
        self._section_label(c, "No-workflow isolation")
        self._hint(
            c,
            "Images without a ComfyUI workflow can be routed to a separate folder "
            "so you can review or handle them independently.",
        ).pack(anchor="w", pady=(0, 8))

        ttk.Checkbutton(
            c, text="Route images without ComfyUI workflow to a separate folder",
            variable=self.sort_no_workflow_var,
            command=self._toggle_no_workflow,
        ).pack(anchor="w")

        self._no_workflow_sub = tk.Frame(c, bg=self.pal["surface"])
        self._hint(
            self._no_workflow_sub,
            "Each output subfolder containing no-workflow images will get a "
            "no-workflow/ subfolder inside it.",
        ).pack(anchor="w", padx=(20, 0), pady=(4, 0))
        self._no_workflow_sub.pack_forget()

        # -- Output hierarchy preview ------------------------------------------
        card = Card(p, self); card.pack(fill="x", pady=(0, 14))
        c = card.content(padx=24, pady=14)
        hdr = tk.Frame(c, bg=self.pal["surface"]); hdr.pack(fill="x", pady=(0, 8))
        lbl = tk.Label(hdr, text="Output hierarchy preview",
                       bg=self.pal["surface"], fg=self.pal["text"],
                       font=(self.font_text, 11, "bold"))
        lbl.pack(side="left")
        ttk.Button(hdr, text="Refresh", style="Win11.TButton",
                   command=self._refresh_hierarchy).pack(side="right")

        self.hierarchy_log = scrolledtext.ScrolledText(
            c, height=22, wrap="none", font=("Consolas", 10),
            bg=self.pal["log_bg"], fg=self.pal["text"], relief="flat", bd=0,
            highlightthickness=1, highlightbackground=self.pal["border"],
            padx=10, pady=8,
        )
        self.hierarchy_log.pack(fill="x")
        self.hierarchy_log.configure(state="disabled")
        self.hierarchy_log.tag_configure("hier_root",  foreground=self.pal["accent"],
                                         font=("Consolas", 10, "bold"))
        self.hierarchy_log.tag_configure("hier_dir",   foreground=self.pal["text"])
        self.hierarchy_log.tag_configure("hier_date",  foreground="#22d3ee")
        self.hierarchy_log.tag_configure("hier_nowf",  foreground="#f59e0b",
                                         font=("Consolas", 10, "bold"))
        self.hierarchy_log.tag_configure("hier_copy",  foreground="#a855f7")
        self.hierarchy_log.tag_configure("hier_total", foreground=self.pal["text_muted"])

        legend_row = tk.Frame(c, bg=self.pal["surface"])
        legend_row.pack(fill="x", pady=(6, 0))
        tk.Label(legend_row, text="Legend:", bg=self.pal["surface"],
                 fg=self.pal["text_muted"], font=(self.font_text, 9)).pack(side="left", padx=(0, 10))
        for _leg_text, _leg_color in [
            ("● Output folder",           self.pal["text"]),
            ("● Date subfolder",          "#22d3ee"),
            ("● no-workflow/ folder",     "#f59e0b"),
            ("● Copied (non-convertible)", "#a855f7"),
        ]:
            tk.Label(legend_row, text=_leg_text, bg=self.pal["surface"],
                     fg=_leg_color, font=(self.font_text, 9)).pack(side="left", padx=(0, 14))

        self._toggle_dest_mode()
        self._toggle_date_sort_options()

    def _get_source_display_path(self):
        """Retourne le chemin source à afficher quand same_dir est actif."""
        if self.source_paths:
            if self.source_is_folder:
                return str(self.source_paths[0])
            return str(self.source_paths[0].parent)
        return "(next to source files)"

    def _pick_output(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_var.set(path)
            self._manual_output = path

    def _toggle_output(self):
        """Legacy compat: called from _toggle_dest_mode."""
        self._toggle_dest_mode()

    def _toggle_dest_mode(self):
        mode = self.dest_mode_var.get()
        # Update same_dir_var for backward compat with downstream code
        self.same_dir_var.set(mode == "same")
        if mode == "custom":
            self._custom_path_row.pack(fill="x", pady=(8, 0))
            self.output_var.set(self._manual_output)
        else:
            self._custom_path_row.pack_forget()
            if mode == "default":
                self.output_var.set(str(DEFAULT_OUTPUT))
                self._manual_output = str(DEFAULT_OUTPUT)
            else:
                self.output_var.set(self._get_source_display_path())
        self._update_source_controls()
        # Don't auto-refresh hierarchy (user uses button)

    def _toggle_package_mode(self):
        if self.package_mode_var.get() == "custom":
            self.package_entry.state(["!disabled"])
        else:
            self.package_entry.state(["disabled"])

    def _toggle_date_sort_options(self):
        sort = self.date_sort_var.get()
        if sort == "none":
            self._date_sub_frame.pack_forget()
        else:
            self._date_sub_frame.pack(fill="x", pady=(4, 0))
            if sort == "day":
                self._date_month_frame.pack_forget()
                self._date_day_frame.pack(fill="x")
            else:
                self._date_day_frame.pack_forget()
                self._date_month_frame.pack(fill="x")

    def _toggle_package(self):
        if self.package_var.get():
            self._package_sub.pack(fill="x", pady=(0, 4))
            self._toggle_package_mode()
        else:
            self._package_sub.pack_forget()

    def _toggle_no_workflow(self):
        if self.sort_no_workflow_var.get():
            self._no_workflow_sub.pack(fill="x", pady=(4, 0))
        else:
            self._no_workflow_sub.pack_forget()

    # -- Page 3 : Reglages -------------------------------------------------

    def _build_page_settings(self):
        p = self.pages["settings"]

        card = Card(p, self); card.pack(fill="x", pady=(0, 24))
        c = card.content()
        self._section_label(c, "Format")

        row = tk.Frame(c, bg=self.pal["surface"]); row.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(row, text="WEBP", variable=self.format_var, value="webp",
                        command=self._on_settings_changed).pack(side="left")
        tk.Label(row, text="  Recommended  ", bg=self.pal["accent_subtle"],
                 fg=self.pal["accent_text"], font=(self.font_text, 10, "bold"),
                 ).pack(side="left", padx=(10, 24), ipady=2)
        ttk.Radiobutton(row, text="JPG", variable=self.format_var, value="jpg",
                        command=self._on_settings_changed).pack(side="left")

        self.format_hint = self._hint(c, "")
        self.format_hint.pack(anchor="w")

        card = Card(p, self); card.pack(fill="x")
        c = card.content()

        head = tk.Frame(c, bg=self.pal["surface"]); head.pack(fill="x", pady=(0, 4))
        tk.Label(head, text="Quality", bg=self.pal["surface"], fg=self.pal["text"],
                 font=(self.font_text, 11, "bold")).pack(side="left")
        self.quality_value_label = tk.Label(
            head, text="90", bg=self.pal["surface"], fg=self.pal["accent"],
            font=(self.font_display, 20, "bold"),
        )
        self.quality_value_label.pack(side="right")

        ttk.Scale(c, from_=25, to=100, orient="horizontal",
                  variable=self.quality_var, command=self._on_quality_change
                  ).pack(fill="x", pady=(2, 4))

        # Colored quality zone gradient
        self._quality_grad = tk.Canvas(c, height=6, bd=0, highlightthickness=0,
                                        bg=self.pal["surface"])
        self._quality_grad.pack(fill="x", pady=(0, 2))
        self._quality_grad.bind("<Configure>",
                                lambda _e: self._draw_quality_gradient())

        leg = tk.Frame(c, bg=self.pal["surface"]); leg.pack(fill="x", pady=(0, 10))
        tk.Label(leg, text="Smaller file", bg=self.pal["surface"], fg=self.pal["text_muted"],
                 font=(self.font_text, 10)).pack(side="left")
        tk.Label(leg, text="Higher fidelity", bg=self.pal["surface"], fg=self.pal["text_muted"],
                 font=(self.font_text, 10)).pack(side="right")

        self.quality_hint = self._hint(c, "")
        self.quality_hint.pack(anchor="w", pady=(0, 10))

        ttk.Checkbutton(
            c, text="Lossless (WEBP) - not readable by ComfyUI drag and drop",
            variable=self.lossless_var, command=self._on_settings_changed,
        ).pack(anchor="w")

        self._on_quality_change(90)

    def _on_quality_change(self, val):
        v = int(float(val))
        self.quality_var.set(v)
        if hasattr(self, "quality_value_label"):
            self.quality_value_label.config(text=str(v))
        self._on_settings_changed()
        self._draw_quality_gradient()

    def _draw_quality_gradient(self):
        if not hasattr(self, "_quality_grad"):
            return
        canvas = self._quality_grad
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1:
            return
        canvas.delete("all")
        # Quality range: 25 → 100 (75 steps)
        # Color stops: (position 0-1, RGB)
        stops = [
            (0.00, (200, 60,  60)),   # 25: red
            (0.40, (220, 140, 30)),   # ~55: orange
            (0.60, (180, 180, 30)),   # ~70: yellow
            (0.87, (60,  180, 80)),   # ~90: green
            (1.00, (60,  140, 220)),  # 100: blue
        ]
        segs = 60
        for s in range(segs):
            t = (s + 0.5) / segs
            x1 = w * s // segs
            x2 = w * (s + 1) // segs
            # Interpolate color
            col = stops[0][1]
            for i in range(len(stops) - 1):
                t0, c0 = stops[i]
                t1, c1 = stops[i + 1]
                if t0 <= t <= t1:
                    ratio = (t - t0) / (t1 - t0)
                    col = tuple(int(c0[j] + (c1[j] - c0[j]) * ratio) for j in range(3))
                    break
            canvas.create_rectangle(x1, 0, x2, h, fill=f"#{col[0]:02x}{col[1]:02x}{col[2]:02x}", outline="")


    def _on_settings_changed(self):
        if not hasattr(self, "format_hint"):
            return
        fmt = self.format_var.get()
        q = self.quality_var.get()
        lossless = self.lossless_var.get()

        if fmt == "webp":
            self.format_hint.config(
                text="Better compression than JPG, supports transparency, readable by ComfyUI."
            )
        else:
            self.format_hint.config(
                text="Works everywhere, about 30% larger than WEBP at similar quality."
            )

        if lossless and fmt == "webp":
            qhint = "Around 50% compression. Perfect quality, but ComfyUI will not read the workflow."
        elif q >= 95:
            qhint = "No visible difference even at 300% zoom. Usually larger than needed."
        elif q >= 88:
            qhint = "Indistinguishable from PNG in A/B comparison for most images."
        elif q >= 80:
            qhint = "Small differences may appear at 200% zoom on fine details."
        elif q >= 70:
            qhint = "Visible artifacts may appear on smooth gradients and transitions."
        elif q >= 60:
            qhint = "Visible artifacts may appear on smooth gradients and transitions."
        elif q >= 50:
            qhint = "Noticeable quality loss. Best for secondary / archival copies."
        else:
            qhint = "Strong compression artifacts. Intended for small preview copies."

        if fmt == "jpg":
            qhint += "    ·  Speed: very fast."
        elif lossless:
            qhint += "    ·  Speed: slow."
        else:
            qhint += "    ·  Speed: normal."

        self.quality_hint.config(text=qhint)
        self._refresh_stats()
        self._schedule_preview_refresh()

    def _schedule_preview_refresh(self):
        if not hasattr(self, "preview_status") or self.preview_image_path is None:
            return
        if self._preview_refresh_after is not None:
            try:
                self.root.after_cancel(self._preview_refresh_after)
            except Exception:
                pass
        self.preview_status.config(text="Updating preview...",
                                   fg=self.pal["text_muted"])
        self._preview_refresh_after = self.root.after(350, self._render_preview)

    # -- Page 4 : Apercu ---------------------------------------------------

    def _build_page_preview(self):
        p = self.pages["preview"]

        card = Card(p, self); card.pack(fill="x", pady=(0, 12))
        c = card.content()

        row = tk.Frame(c, bg=self.pal["surface"]); row.pack(fill="x")
        ttk.Button(row, text="Random image",
                   command=self._pick_random_preview).pack(side="left")
        ttk.Button(row, text="Choose image...",
                   command=self._pick_preview).pack(side="left", padx=(10, 0))
        self.preview_path_label = tk.Label(
            row, text="No source image", bg=self.pal["surface"],
            fg=self.pal["text_secondary"], font=(self.font_text, 10),
        )
        self.preview_path_label.pack(side="left", padx=(12, 0))

        zoom_row = tk.Frame(c, bg=self.pal["surface"]); zoom_row.pack(fill="x", pady=(14, 0))
        tk.Label(zoom_row, text="Zoom :", bg=self.pal["surface"], fg=self.pal["text"],
                 font=(self.font_text, 10)).pack(side="left", padx=(0, 12))
        for lab, val in [("50 %", 0.5), ("100 %", 1.0), ("200 %", 2.0),
                         ("300 %", 3.0), ("400 %", 4.0)]:
            ttk.Radiobutton(zoom_row, text=lab, variable=self.preview_zoom, value=val,
                            command=self._on_preview_zoom).pack(side="left", padx=(0, 12))

        mode_row = tk.Frame(c, bg=self.pal["surface"]); mode_row.pack(fill="x", pady=(12, 0))
        tk.Label(mode_row, text="Mode:", bg=self.pal["surface"], fg=self.pal["text"],
                 font=(self.font_text, 10)).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(mode_row, text="Side by side", variable=self.preview_mode,
                        value="side", command=self._update_preview_mode).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(mode_row, text="Slider", variable=self.preview_mode,
                        value="slider", command=self._update_preview_mode).pack(side="left")

        self._hint(c, "Side by side: hover to pan. Slider: hover to reveal, click and drag to pan."
                   ).pack(anchor="w", pady=(12, 0))

        panels_card = Card(p, self); panels_card.pack(fill="both", expand=True)
        c = panels_card.content(padx=14, pady=14)

        VIEW_W = 320
        VIEW_H = 300
        self.preview_view_width = VIEW_W
        self.preview_view_height = VIEW_H
        self.preview_panel = c
        self.side_wrap = tk.Frame(c, bg=self.pal["surface"])
        self.side_wrap.pack(fill="both", expand=True)
        self.side_wrap.grid_columnconfigure(0, weight=1, uniform="preview")
        self.side_wrap.grid_columnconfigure(1, weight=1, uniform="preview")
        self.side_wrap.grid_rowconfigure(0, weight=1)

        left = tk.Frame(self.side_wrap, bg=self.pal["surface"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        tk.Label(left, text="Original PNG", bg=self.pal["surface"], fg=self.pal["text"],
                 font=(self.font_text, 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.preview_canvas_left = tk.Canvas(left, width=VIEW_W, height=VIEW_H,
                                             bg="#000", highlightthickness=1,
                                             highlightbackground=self.pal["border"])
        self.preview_canvas_left.pack(fill="both", expand=True)
        self.preview_canvas_left.bind("<Motion>", self._on_preview_motion)
        self.preview_canvas_left.bind("<Leave>", self._on_preview_leave)
        self.preview_canvas_left.bind("<Configure>", self._on_preview_canvas_resize)
        self.preview_label_left = tk.Label(left, text="—", bg=self.pal["surface"],
                                           fg=self.pal["text_secondary"], font=(self.font_text, 10))
        self.preview_label_left.pack(pady=(6, 0))

        right = tk.Frame(self.side_wrap, bg=self.pal["surface"])
        right.grid(row=0, column=1, sticky="nsew")
        self.preview_right_title = tk.Label(right, text="Converted", bg=self.pal["surface"],
                                            fg=self.pal["text"], font=(self.font_text, 10, "bold"))
        self.preview_right_title.pack(anchor="w", pady=(0, 6))
        self.preview_canvas_right = tk.Canvas(right, width=VIEW_W, height=VIEW_H,
                                              bg="#000", highlightthickness=1,
                                              highlightbackground=self.pal["border"])
        self.preview_canvas_right.pack(fill="both", expand=True)
        self.preview_canvas_right.bind("<Motion>", self._on_preview_motion)
        self.preview_canvas_right.bind("<Leave>", self._on_preview_leave)
        self.preview_canvas_right.bind("<Configure>", self._on_preview_canvas_resize)
        self.preview_label_right = tk.Label(right, text="—", bg=self.pal["surface"],
                                            fg=self.pal["text_secondary"], font=(self.font_text, 10))
        self.preview_label_right.pack(pady=(6, 0))

        self.slider_wrap = tk.Frame(c, bg=self.pal["surface"])
        self.preview_slider_title = tk.Label(
            self.slider_wrap, text="Original / Converted", bg=self.pal["surface"],
            fg=self.pal["text"], font=(self.font_text, 10, "bold"),
        )
        self.preview_slider_title.pack(anchor="w", pady=(0, 6))
        self.preview_canvas_slider = tk.Canvas(
            self.slider_wrap, width=VIEW_W * 2, height=VIEW_H,
            bg="#000", highlightthickness=1, highlightbackground=self.pal["border"],
            cursor="sb_h_double_arrow",
        )
        self.preview_canvas_slider.pack(fill="both", expand=True)
        self.preview_canvas_slider.bind("<Motion>", self._on_slider_motion)
        self.preview_canvas_slider.bind("<ButtonPress-1>", self._on_slider_press)
        self.preview_canvas_slider.bind("<B1-Motion>", self._on_slider_drag)
        self.preview_canvas_slider.bind("<ButtonRelease-1>", self._on_slider_release)
        self.preview_canvas_slider.bind("<Configure>", self._on_preview_canvas_resize)
        self.preview_label_slider = tk.Label(
            self.slider_wrap, text="—", bg=self.pal["surface"],
            fg=self.pal["text_secondary"], font=(self.font_text, 10),
        )
        self.preview_label_slider.pack(pady=(6, 0))

        self.preview_status = tk.Label(c, text="Choose a source to generate a preview.",
                                       bg=self.pal["surface"], fg=self.pal["text_muted"],
                                       font=(self.font_text, 10))
        self.preview_status.pack(pady=(10, 0))
        self._update_preview_mode()

    def _update_preview_mode(self):
        if not hasattr(self, "side_wrap"):
            return
        if self.preview_mode.get() == "slider":
            self.side_wrap.pack_forget()
            self.slider_wrap.pack(fill="both", expand=True)
            self.preview_status.config(
                text="Hover to move the comparison slider. Click and drag to pan.",
                fg=self.pal["text_muted"],
            )
        else:
            self.slider_wrap.pack_forget()
            self.side_wrap.pack(fill="both", expand=True)
            self.preview_status.config(
                text="Hover either preview to pan through the image.",
                fg=self.pal["text_muted"],
            )
        self.root.after_idle(lambda: self._show_preview_at(*self._preview_pan))

    def _active_preview_size(self):
        if self.preview_mode.get() == "slider" and hasattr(self, "preview_canvas_slider"):
            canvas = self.preview_canvas_slider
        else:
            canvas = self.preview_canvas_left
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        if width <= 1 or height <= 1:
            width = self.preview_view_width
            height = self.preview_view_height
        return width, height

    def _on_preview_canvas_resize(self, event):
        if event.width <= 1 or event.height <= 1:
            return
        if (abs(event.width - self.preview_view_width) < 2 and
                abs(event.height - self.preview_view_height) < 2):
            return
        self.preview_view_width = event.width
        self.preview_view_height = event.height
        self._show_preview_at(*self._preview_pan)

    def _reset_preview(self):
        self.preview_image_path = None
        self._preview_original_full = None
        self._preview_converted_full = None
        self._preview_original_bytes = 0
        self._preview_converted_bytes = 0
        self._preview_pan = (0.5, 0.5)
        self.preview_path_label.config(text="No source image",
                                       fg=self.pal["text_secondary"])
        self.preview_label_left.config(text="—")
        self.preview_label_right.config(text="—")
        self.preview_label_slider.config(text="—")
        self.preview_canvas_left.delete("all")
        self.preview_canvas_right.delete("all")
        self.preview_canvas_slider.delete("all")
        self.preview_status.config(text="Choose a source to generate a preview.",
                                   fg=self.pal["text_muted"])

    def _set_preview_image(self, path):
        if self._preview_pending:
            return
        self.preview_image_path = Path(path)
        self._preview_pan = (0.5, 0.5)
        self.preview_path_label.config(text=self.preview_image_path.name,
                                       fg=self.pal["text"])
        self._render_preview()

    def _pick_random_preview(self, auto=False):
        if not self.scanned_files:
            self._reset_preview()
            return
        choices = list(self.scanned_files)
        if self.preview_image_path in choices and len(choices) > 1:
            choices = [p for p in choices if p != self.preview_image_path]
        self._set_preview_image(random.choice(choices))

    def _pick_preview(self):
        initial = ""
        if self.scanned_files:
            initial = str(self.scanned_files[0])
        path = filedialog.askopenfilename(
            title="Choose an image for preview",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")],
            initialfile=initial,
        )
        if path:
            self._set_preview_image(path)

    def _on_preview_zoom(self):
        if self._preview_original_full is not None:
            self._show_preview_at(*self._preview_pan)
        else:
            self._render_preview()

    def _render_preview(self):
        self._preview_refresh_after = None
        if self.preview_image_path is None or self._preview_pending:
            return
        self._preview_pending = True
        fmt = self.format_var.get()
        q = self.quality_var.get()
        lossless = self.lossless_var.get()
        path = self.preview_image_path
        self.preview_right_title.config(text=f"Converted  ({fmt.upper()} q{q})")
        self.preview_status.config(text="Rendering preview...", fg=self.pal["text_muted"])
        threading.Thread(
            target=self._preview_worker,
            args=(path, fmt, q, lossless),
            daemon=True,
        ).start()

    def _preview_worker(self, path, fmt, quality, lossless):
        try:
            orig = Image.open(path)
            orig.load()
            converted_bytes = convert_to_bytes(
                orig.copy(), fmt, quality, lossless=lossless,
            )
            conv = Image.open(BytesIO(converted_bytes))
            conv.load()
            os_b = path.stat().st_size
            cs_b = len(converted_bytes)
            ratio = (1 - cs_b / os_b) * 100 if os_b else 0
            self.root.after(0, self._apply_preview, path, orig, conv, os_b, cs_b, ratio)
        except Exception as e:
            self.root.after(0, lambda: self.preview_status.config(
                text=f"Error: {e}", fg=self.pal["danger"]))
            self._preview_pending = False

    def _crop_preview(self, img, xratio, yratio, view_w, view_h):
        zoom = max(0.5, float(self.preview_zoom.get()))
        # Cap : ne pas upscaler au-delà de la taille naturelle à ce niveau de zoom
        natural_w = int(img.width * zoom)
        natural_h = int(img.height * zoom)
        disp_w = min(view_w, natural_w)
        disp_h = min(view_h, natural_h)
        crop_w = max(1, min(img.width, round(disp_w / zoom)))
        crop_h = max(1, min(img.height, round(disp_h / zoom)))
        max_left = max(0, img.width - crop_w)
        max_top = max(0, img.height - crop_h)
        left = int(max_left * xratio)
        top = int(max_top * yratio)
        crop = img.crop((left, top, left + crop_w, top + crop_h))
        method = Image.NEAREST if zoom > 1 else Image.LANCZOS
        if crop.size != (disp_w, disp_h):
            crop = crop.resize((disp_w, disp_h), method)
        if disp_w < view_w or disp_h < view_h:
            mode = "RGBA" if img.mode == "RGBA" else "RGB"
            fill = (0, 0, 0, 255) if mode == "RGBA" else (0, 0, 0)
            bg = Image.new(mode, (view_w, view_h), fill)
            bg.paste(crop, ((view_w - disp_w) // 2, (view_h - disp_h) // 2))
            return bg
        return crop

    def _canvas_size(self, canvas):
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        if width <= 1 or height <= 1:
            return self.preview_view_width, self.preview_view_height
        return width, height

    def _render_slider_image(self, xratio, yratio):
        width, height = self._canvas_size(self.preview_canvas_slider)
        orig = self._crop_preview(self._preview_original_full, xratio, yratio, width, height)
        conv = self._crop_preview(self._preview_converted_full, xratio, yratio, width, height)
        split_x = max(0, min(width, int(width * self._preview_split)))
        merged = Image.new("RGBA", (width, height))
        merged.alpha_composite(conv.convert("RGBA"))
        if split_x > 0:
            merged.alpha_composite(orig.convert("RGBA").crop((0, 0, split_x, height)), (0, 0))
        d = ImageDraw.Draw(merged)
        d.line((split_x, 0, split_x, height), fill="#ffffff", width=2)
        d.line((split_x - 1, 0, split_x - 1, height), fill="#1a1a1a", width=1)
        handle_y = height // 2
        d.ellipse((split_x - 9, handle_y - 22, split_x + 9, handle_y - 4),
                  fill="#ffffff", outline="#707070")
        d.ellipse((split_x - 9, handle_y + 4, split_x + 9, handle_y + 22),
                  fill="#ffffff", outline="#707070")
        return merged

    def _show_preview_at(self, xratio, yratio):
        if self._preview_original_full is None or self._preview_converted_full is None:
            return
        xratio = max(0, min(1, xratio))
        yratio = max(0, min(1, yratio))
        self._preview_pan = (xratio, yratio)
        if self.preview_mode.get() == "slider":
            merged = self._render_slider_image(xratio, yratio)
            self._preview_photo_slider = ImageTk.PhotoImage(merged)
            width, height = merged.size
            self.preview_canvas_slider.delete("all")
            self.preview_canvas_slider.create_image(width // 2, height // 2,
                                                    image=self._preview_photo_slider)
            return

        left_w, left_h = self._canvas_size(self.preview_canvas_left)
        right_w, right_h = self._canvas_size(self.preview_canvas_right)
        orig = self._crop_preview(self._preview_original_full, xratio, yratio, left_w, left_h)
        conv = self._crop_preview(self._preview_converted_full, xratio, yratio, right_w, right_h)
        self._preview_photo_left = ImageTk.PhotoImage(orig)
        self._preview_photo_right = ImageTk.PhotoImage(conv)
        self.preview_canvas_left.delete("all")
        self.preview_canvas_right.delete("all")
        self.preview_canvas_left.create_image(left_w // 2, left_h // 2, image=self._preview_photo_left)
        self.preview_canvas_right.create_image(right_w // 2, right_h // 2, image=self._preview_photo_right)

    def _on_preview_motion(self, event):
        width, height = self._canvas_size(event.widget)
        self._show_preview_at(event.x / width, event.y / height)

    def _on_preview_leave(self, _):
        self.preview_status.config(
            text="Hover either preview to pan through the image.",
            fg=self.pal["text_muted"],
        )

    def _on_slider_motion(self, event):
        if self._slider_dragging:
            return
        width, _ = self._canvas_size(self.preview_canvas_slider)
        self._preview_split = max(0, min(1, event.x / width))
        self._show_preview_at(*self._preview_pan)

    def _on_slider_press(self, event):
        self._slider_dragging = True
        self._on_slider_drag(event)

    def _on_slider_drag(self, event):
        if not self._slider_dragging:
            return
        width, height = self._canvas_size(self.preview_canvas_slider)
        self._show_preview_at(event.x / width, event.y / height)

    def _on_slider_release(self, _):
        self._slider_dragging = False

    def _apply_preview(self, path, orig, conv, os_b, cs_b, ratio):
        if path != self.preview_image_path:
            self._preview_pending = False
            return
        self._preview_original_full = orig
        self._preview_converted_full = conv
        self._preview_original_bytes = os_b
        self._preview_converted_bytes = cs_b
        self._show_preview_at(*self._preview_pan)
        self.preview_label_left.config(text=human_size(os_b))
        self.preview_label_right.config(text=f"{human_size(cs_b)}  (-{ratio:.0f} %)")
        self.preview_label_slider.config(
            text=f"{human_size(os_b)} original · {human_size(cs_b)} converted  (-{ratio:.0f} %)"
        )
        self.preview_status.config(
            text=("Hover to move the comparison slider. Click and drag to pan."
                  if self.preview_mode.get() == "slider"
                  else "Hover either preview to pan through the image."),
            fg=self.pal["text_muted"],
        )
        self._preview_pending = False

    # -- Page 5 : Convertir ------------------------------------------------

    def _build_page_convert(self):
        p = self._scrollable_page(self.pages["convert"])

        # ── Run (premier bloc) ────────────────────────────────────────────────
        card = Card(p, self); card.pack(fill="x", pady=(0, 14))
        c = card.content()
        self._section_label(c, "Run")

        btn_row = tk.Frame(c, bg=self.pal["surface"]); btn_row.pack(fill="x", pady=(0, 12))
        self.convert_btn = ttk.Button(
            btn_row, text="  Convert now  ", command=self._start_convert,
            style="Accent.TButton",
        )
        self.convert_btn.pack(side="left")
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self._stop_convert,
                                   style="Win11.TButton")
        self.open_output_btn = ttk.Button(
            btn_row, text="Open output folder", command=self._open_output_folder,
            style="Win11.TButton",
        )

        self.progress = FancyProgressBar(c, self)
        self.progress.pack(fill="x", pady=(0, 8))
        self.status_label = tk.Label(c, text="Ready.", bg=self.pal["surface"],
                                     fg=self.pal["text_secondary"], font=(self.font_text, 10),
                                     anchor="w")
        self.status_label.pack(fill="x")

        # ── Estimation ────────────────────────────────────────────────────────
        card = Card(p, self); card.pack(fill="x", pady=(0, 14))
        c = card.content()
        self._section_label(c, "Estimation")

        stats = tk.Frame(c, bg=self.pal["surface"]); stats.pack(fill="x", pady=(0, 4))
        for attr, label, color_key in [
            ("estim_detected", "DETECTED",         "text"),
            ("estim_after",    "AFTER CONVERSION",  "text"),
            ("estim_saved",    "SPACE SAVED",       "accent"),
        ]:
            col = tk.Frame(stats, bg=self.pal["surface"])
            col.pack(side="left", expand=True, fill="x", padx=(0, 16))
            tk.Label(col, text=label, bg=self.pal["surface"], fg=self.pal["text_muted"],
                     font=(self.font_text, 9, "bold")).pack(anchor="w")
            lbl = tk.Label(col, text="—", bg=self.pal["surface"], fg=self.pal[color_key],
                           font=(self.font_display, 14, "bold"))
            lbl.pack(anchor="w", pady=(2, 0))
            setattr(self, attr, lbl)

        # ── Performance ───────────────────────────────────────────────────────
        card = Card(p, self); card.pack(fill="x", pady=(0, 14))
        c = card.content()
        self._section_label(c, "Performance")

        self._hint(
            c,
            "Conversion runs on CPU via Pillow — no GPU needed for WEBP/JPG encoding.\n"
            "Increase workers to convert multiple files in parallel.",
        ).pack(anchor="w", pady=(0, 12))

        workers_row = tk.Frame(c, bg=self.pal["surface"]); workers_row.pack(fill="x")
        tk.Label(workers_row, text="Parallel workers:", bg=self.pal["surface"],
                 fg=self.pal["text"], font=(self.font_text, 10)).pack(side="left")
        self._workers_val_label = tk.Label(
            workers_row, text="2", bg=self.pal["surface"],
            fg=self.pal["accent"], font=(self.font_display, 16, "bold"))
        self._workers_val_label.pack(side="right")
        ttk.Scale(c, from_=1, to=8, orient="horizontal",
                  variable=self.workers_var,
                  command=lambda v: (
                      self.workers_var.set(round(float(v))),
                      self._workers_val_label.config(text=str(round(float(v))))
                  )).pack(fill="x", pady=(4, 0))
        wleg = tk.Frame(c, bg=self.pal["surface"]); wleg.pack(fill="x", pady=(2, 0))
        tk.Label(wleg, text="1 — sequential", bg=self.pal["surface"],
                 fg=self.pal["text_muted"], font=(self.font_text, 10)).pack(side="left")
        tk.Label(wleg, text="8 — max parallel", bg=self.pal["surface"],
                 fg=self.pal["text_muted"], font=(self.font_text, 10)).pack(side="right")

        # ── Strip workflow (zone danger) ──────────────────────────────────────
        danger_bg = "#2c0f0f" if self.theme_mode == "dark" else "#fff0f0"
        danger_card = tk.Frame(
            p, bg=danger_bg,
            highlightbackground=self.pal["danger"], highlightthickness=1, bd=0,
        )
        danger_card.pack(fill="x", pady=(0, 14))
        dc = tk.Frame(danger_card, bg=danger_bg)
        dc.pack(fill="both", expand=True, padx=24, pady=16)

        tk.Label(dc, text="⚠  Strip ComfyUI Workflow Data", bg=danger_bg,
                 fg=self.pal["danger"], font=(self.font_text, 11, "bold")
                 ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            dc,
            text=("Remove embedded workflow and prompt data from output images.\n"
                  "Source PNG files are never modified — only the converted copies are affected."),
            bg=danger_bg, fg=self.pal["text"], font=(self.font_text, 10),
            anchor="w", justify="left", wraplength=600,
        ).pack(anchor="w", pady=(0, 6))

        self.strip_info_label = tk.Label(
            dc, text="Select a source to see estimated additional savings.",
            bg=danger_bg, fg=self.pal["text_muted"], font=(self.font_text, 10, "italic"),
            anchor="w", justify="left",
        )
        self.strip_info_label.pack(anchor="w", pady=(0, 10))

        ttk.Checkbutton(
            dc, text="Strip workflow and prompt data from output images",
            variable=self.strip_workflow_var,
            command=self._toggle_strip_workflow,
        ).pack(anchor="w")

        self._strip_confirm_frame = tk.Frame(dc, bg=danger_bg)
        tk.Frame(self._strip_confirm_frame, bg=self.pal["danger"],
                 height=1).pack(fill="x", pady=(10, 8))
        self._strip_confirm_check = ttk.Checkbutton(
            self._strip_confirm_frame,
            text=("I understand that this will permanently remove ComfyUI workflow data\n"
                  "from the converted output images (source files will NOT be affected)."),
            variable=self.strip_workflow_confirm_var,
            command=self._check_convert_ready,
        )
        self._strip_confirm_check.pack(anchor="w")
        self._strip_confirm_frame.pack(fill="x")
        self._strip_confirm_frame.pack_forget()

        # ── Log ───────────────────────────────────────────────────────────────
        card = Card(p, self); card.pack(fill="x", pady=(0, 4))
        c = card.content()
        self._section_label(c, "Log")
        self.log = tk.Text(
            c, height=10, wrap="word", font=("Consolas", 10),
            bg=self.pal["log_bg"], fg=self.pal["text"], relief="flat", bd=0,
            highlightthickness=1, highlightbackground=self.pal["border"],
            highlightcolor=self.pal["border"], padx=10, pady=8,
            insertbackground=self.pal["text"],
        )
        self.log.pack(fill="x")
        self.log.configure(state="disabled")
        self.log.tag_configure("log_header", foreground=self.pal["text_muted"])
        self.log.tag_configure("log_copy",   foreground="#60a5fa")
        self.log.tag_configure("log_nowf",   foreground="#f59e0b")
        self.log.tag_configure("log_err",    foreground="#ef4444")
        self.log.tag_configure("log_ok",     foreground="#22c55e")

        self._update_strip_info()

    def _toggle_strip_workflow(self):
        if self.strip_workflow_var.get():
            self._strip_confirm_frame.pack(fill="x")
        else:
            self.strip_workflow_confirm_var.set(False)
            self._strip_confirm_frame.pack_forget()
        self._check_convert_ready()

    def _check_convert_ready(self):
        if not hasattr(self, "convert_btn"):
            return
        if self.is_running:
            return
        blocked = self.strip_workflow_var.get() and not self.strip_workflow_confirm_var.get()
        self.convert_btn.configure(state="disabled" if blocked else "normal")

    def _update_strip_info(self):
        if not hasattr(self, "strip_info_label"):
            return
        if self._total_workflow_bytes > 0 and self._workflow_file_count > 0:
            self.strip_info_label.config(
                text=(f"~{human_size(self._total_workflow_bytes)} additional space saved  "
                      f"({self._workflow_file_count} image(s) with workflow data)")
            )
        else:
            self.strip_info_label.config(
                text="Select a source to see estimated additional savings."
            )

    # -- Hiérarchie de sortie -----------------------------------------------

    def _refresh_hierarchy(self):
        if not hasattr(self, "hierarchy_log"):
            return
        lines = self._build_hierarchy_lines()
        self.hierarchy_log.configure(state="normal")
        self.hierarchy_log.delete("1.0", "end")
        for text, tag in lines:
            if tag:
                self.hierarchy_log.insert("end", text + "\n", tag)
            else:
                self.hierarchy_log.insert("end", text + "\n")
        self.hierarchy_log.configure(state="disabled")


    def _build_hierarchy_lines(self):
        return build_hierarchy_lines(HierarchyParams(
            scanned_files=self.scanned_files,
            source_paths=self.source_paths,
            source_is_folder=self.source_is_folder,
            date_sort=self.date_sort_var.get(),
            preserve=self.preserve_var.get(),
            fmt=self.format_var.get(),
            quality=self.quality_var.get(),
            lossless=self.lossless_var.get(),
            recursive=self.recursive_var.get(),
            dest_mode=self.dest_mode_var.get(),
            custom_output=self.output_var.get(),
            default_output=DEFAULT_OUTPUT,
            package_subfolder=self._resolve_package_name(),
            date_force_year=self.date_force_year_var.get(),
            date_day_style=self.date_day_style_var.get(),
            date_placement=self.date_placement_var.get(),
            sort_no_workflow=self.sort_no_workflow_var.get(),
            files_without_workflow=self._files_without_workflow,
            copy_unsupported=self.copy_unsupported_var.get(),
            unsupported_files=self._unsupported_files,
        ))

    def _build_file_tree_text(self, files, max_per_folder=30):
        root = (self.source_paths[0] if self.source_is_folder and self.source_paths else None)
        return build_file_tree_text(files, source_root=root, max_per_folder=max_per_folder)

    # -- Estimation --------------------------------------------------------

    def _refresh_stats(self):
        if not hasattr(self, "estim_detected"):
            return
        if not self.scanned_files:
            self.estim_detected.config(text="—")
            self.estim_after.config(text="—")
            self.estim_saved.config(text="—")
            return

        n = len(self.scanned_files)
        total = self.scanned_total_bytes
        factor = estimate_factor(self.format_var.get(), self.quality_var.get(),
                                 lossless=self.lossless_var.get())
        after = int(total * factor)
        saved = total - after
        ratio = (1 - factor) * 100
        self.estim_detected.config(text=f"{n}  ·  {human_size(total)}")
        self.estim_after.config(text=f"~ {human_size(after)}")
        self.estim_saved.config(text=f"~ {human_size(saved)}  (-{ratio:.0f}%)")

    # -- Conversion --------------------------------------------------------

    def _log(self, msg, tag=None):
        self.log_queue.put((msg, tag))

    def _poll_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                msg, tag = item if isinstance(item, tuple) else (item, None)
                if hasattr(self, "log"):
                    self.log.configure(state="normal")
                    self.log.insert("end", msg + "\n", (tag,) if tag else ())
                    line_count = int(self.log.index("end-1c").split(".")[0])
                    self.log.configure(height=max(10, line_count))
                    self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log_queue)

    def _format_eta(self, seconds):
        if seconds < 1:
            return "<1s"
        m, s = divmod(int(seconds), 60)
        if m == 0:
            return f"{s}s"
        return f"{m}m{s:02d}s"

    def _resolve_package_name(self):
        if not self.package_var.get():
            return None
        if hasattr(self, "package_mode_var") and self.package_mode_var.get() == "custom":
            name = self.package_name_var.get().strip()
            return name if name else "converted"
        if self.source_is_folder and self.source_paths:
            return self.source_paths[0].name
        return "converted"

    def _start_convert(self):
        if self.is_running:
            return
        if not self.scanned_files:
            self._log("[!] No source selected. Go to Source and choose one.")
            self._goto_page("source")
            return

        if self.strip_workflow_var.get() and not self.strip_workflow_confirm_var.get():
            self._log("[!] Please confirm the strip workflow option before converting.")
            return

        mode = self.dest_mode_var.get()
        if mode == "same":
            output = None
        elif mode == "default":
            output = str(DEFAULT_OUTPUT)
        else:
            output = self.output_var.get().strip()
            if not output:
                self._log("[!] Output folder is empty.")
                return
            try:
                Path(output).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self._log(f"[!] Output folder is not accessible: {e}")
                return

        sources = self.source_paths[0] if self.source_is_folder else self.source_paths
        package = self._resolve_package_name()

        if output is not None:
            safe_pkg = ("".join(c for c in package if c not in r'<>:"/\|?*').strip()
                        if package else "")
            self._last_output_dir = str(Path(output) / safe_pkg) if safe_pkg else output
        else:
            self._last_output_dir = None

        self.is_running = True
        self.stop_event.clear()
        self.convert_btn.configure(state="disabled")
        self.open_output_btn.pack_forget()
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.progress.configure(value=0, maximum=100)
        self.progress.start_anim()

        files_to_copy = list(self._unsupported_files) if self.copy_unsupported_var.get() else []

        no_workflow_files = None
        if (self.sort_no_workflow_var.get()
                and self._files_without_workflow
                and output is not None):
            no_workflow_files = list(self._files_without_workflow)

        thread = threading.Thread(
            target=self._run_convert,
            args=(sources, output, self.format_var.get(), self.quality_var.get(),
                  self.lossless_var.get(), self.recursive_var.get(),
                  self.preserve_var.get(), package, self.date_sort_var.get(),
                  self.date_day_style_var.get(), self.date_placement_var.get(),
                  self.strip_workflow_var.get(), files_to_copy,
                  self.workers_var.get(), self.date_force_year_var.get(),
                  no_workflow_files),
            daemon=True,
        )
        thread.start()

    def _stop_convert(self):
        if self.is_running:
            self.stop_event.set()
            self._log("[stop requested...]")

    def _run_convert(self, sources, output, fmt, quality, lossless, recursive,
                     preserve, package, date_sort, date_day_style, date_placement,
                     strip_workflow, files_to_copy=None, workers=2, force_year_prefix=False,
                     no_workflow_files=None):
        params = f"{fmt.upper()} q{quality}" + (" lossless" if lossless else "")
        if package:
            params += f" -> subfolder '{package}'"
        if date_sort != "none":
            params += f" · sorted by {date_sort}"
            if date_placement == "leaf":
                params += " (within subfolders)"
        if strip_workflow:
            params += " · workflow stripped"
        if no_workflow_files:
            params += " · no-workflow → no-workflow/ per folder"
        self._log(f"--- Started: {params} ---", "log_header")
        if files_to_copy:
            self._log(f"  {len(files_to_copy)} non-convertible file(s) will be copied as-is", "log_copy")

        def cb(i, total, name, msg, elapsed, eta, is_no_wf=False):
            if total > 0:
                self.root.after(0, lambda: self.progress.configure(maximum=total, value=i))
                status = f"{i} / {total}    ·    ETA {self._format_eta(eta)}"
                self.root.after(0, lambda s=status: self.status_label.config(text=s))
            if name:
                low = msg.lower()
                if "failed" in low or "error" in low or "echou" in low:
                    tag = "log_err"
                elif is_no_wf:
                    tag = "log_nowf"
                else:
                    tag = None
                self._log(f"  [{i}/{total}] {name}  {msg}", tag)
            else:
                self._log(f"  {msg}", "log_header")

        def copy_cb(src, dst, success):
            if success:
                self._log(f"  [copy] {src.name}", "log_copy")
            else:
                self._log(f"  [copy failed] {src.name}", "log_err")

        try:
            result = batch_convert(
                sources, output_dir=output, fmt=fmt, quality=quality,
                lossless=lossless, recursive=recursive,
                preserve_structure=preserve, package_subfolder=package,
                date_sort=date_sort, date_day_style=date_day_style,
                date_placement=date_placement, strip_workflow=strip_workflow,
                files_to_copy=files_to_copy or [],
                workers=workers, force_year_prefix=force_year_prefix,
                progress_callback=cb, stop_event=self.stop_event,
                no_workflow_files=no_workflow_files,
                copy_callback=copy_cb,
            )
            status_word = "Stopped" if result.get("stopped") else "Done"
            saved = human_size(result.get("saved_bytes", 0))
            summary = (f"--- {status_word}: {result['success']}/{result['total']} successful, "
                       f"{result['failed']} failed · {saved} saved ---")
            self._log(summary, "log_header")
            self.root.after(0, lambda: self.status_label.config(
                text=f"{status_word}. {result['success']}/{result['total']} converted, {saved} saved."
            ))
        except Exception as e:
            self._log(f"[!] Error: {e}")
        finally:
            self.is_running = False
            self.root.after(0, self._reset_buttons)

    def _reset_buttons(self):
        self.progress.stop_anim()
        self.stop_btn.pack_forget()
        self._check_convert_ready()
        if self._last_output_dir:
            self.open_output_btn.pack(side="left", padx=(8, 0))
        else:
            self.open_output_btn.pack_forget()

    def _open_output_folder(self):
        if self._last_output_dir:
            import subprocess
            subprocess.Popen(["explorer", str(Path(self._last_output_dir))])


def main():
    global _splash
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("ShrinkComfy.App")
        except Exception:
            pass
    root = _splash
    _splash = None
    for w in root.winfo_children():
        w.destroy()
    root.overrideredirect(False)
    root.withdraw()
    root.attributes("-topmost", False)
    ConverterApp(root)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()

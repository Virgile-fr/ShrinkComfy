"""
Logique de prévisualisation de l'arborescence de sortie.
Extrait de gui.py — ne dépend pas de tkinter.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from convert import _date_subdir, estimate_factor, scan_sources
from utils import human_size


@dataclass
class HierarchyParams:
    scanned_files: List[Path]
    source_paths: List[Path]
    source_is_folder: bool
    date_sort: str
    preserve: bool
    fmt: str
    quality: int
    lossless: bool
    recursive: bool
    dest_mode: str               # "same" | "default" | "custom"
    custom_output: str
    default_output: Path
    package_subfolder: Optional[str]
    date_force_year: bool
    date_day_style: str
    date_placement: str
    sort_no_workflow: bool
    files_without_workflow: List[Path]
    copy_unsupported: bool
    unsupported_files: List[Path]


# ---------------------------------------------------------------------------
# Rendu de l'arbre de sortie
# ---------------------------------------------------------------------------

def render_tree_node(path, children, all_nodes, lines, prefix, is_last, is_root,
                     copy_summaries=None):
    node = all_nodes.get(path, {"count": 0, "est_size": 0})
    is_nowf = node.get("is_nowf", False)
    if is_root:
        connector = ""
        tag = "hier_root"
        label = (f"\U0001F4C1 {path}/   "
                 f"{node['count']} file(s) · ~{human_size(node['est_size'])}")
    else:
        connector = "└── " if is_last else "├── "
        tag = "hier_nowf" if is_nowf else ("hier_date" if node.get("is_date") else "hier_dir")
        label = (f"\U0001F4C1 {path.name}/   "
                 f"{node['count']} file(s) · ~{human_size(node['est_size'])}")
    lines.append((f"{prefix}{connector}{label}", tag))
    kids = sorted(children.get(path, []), key=lambda x: str(x))
    new_prefix = prefix + ("    " if is_last else "│   ")
    has_copy = bool(copy_summaries and path in copy_summaries)
    for i, kid in enumerate(kids):
        kid_is_last = (i == len(kids) - 1) and not has_copy
        render_tree_node(kid, children, all_nodes, lines,
                         new_prefix, kid_is_last, False,
                         copy_summaries=copy_summaries)
    if has_copy:
        info = copy_summaries[path]
        lines.append((
            f"{new_prefix}└── \U0001F4CB "
            f"{info['count']} non-convertible file(s) copied · ~{human_size(info['size'])}",
            "hier_copy",
        ))


# ---------------------------------------------------------------------------
# Arbre des fichiers source (panneau Source)
# ---------------------------------------------------------------------------

def build_file_tree_text(files, source_root=None, max_per_folder=30):
    if not files:
        return ""
    root = source_root
    tree = {}

    def ensure(p):
        if p not in tree:
            tree[p] = {"subdirs": set(), "files": []}

    for f in files:
        ensure(f.parent)
        tree[f.parent]["files"].append(f.name)
        p = f.parent
        while root and p != root and p.parent != p:
            ensure(p.parent)
            tree[p.parent]["subdirs"].add(p)
            p = p.parent
        if root:
            ensure(root)

    lines = []

    def render(path, prefix, is_last, is_root=False):
        if is_root:
            lines.append(f"\U0001F4C1 {path.name}/")
            child_prefix = ""
        else:
            conn = "└── " if is_last else "├── "
            lines.append(f"{prefix}{conn}\U0001F4C1 {path.name}/")
            child_prefix = prefix + ("    " if is_last else "│   ")
        info = tree.get(path, {"subdirs": set(), "files": []})
        subdirs = sorted(info["subdirs"], key=lambda x: x.name)
        fnames = sorted(info["files"])
        shown = fnames[:max_per_folder]
        extra = len(fnames) - max_per_folder
        items = [("d", d) for d in subdirs] + [("f", n) for n in shown]
        if extra > 0:
            items.append(("m", f"… and {extra} more"))
        for i, (kind, item) in enumerate(items):
            last = i == len(items) - 1
            c = "└── " if last else "├── "
            if kind == "d":
                render(item, child_prefix, last)
            elif kind == "f":
                lines.append(f"{child_prefix}{c}\U0001F4C4 {item}")
            else:
                lines.append(f"{child_prefix}{c}{item}")

    if root and root in tree:
        render(root, "", True, is_root=True)
    else:
        groups = defaultdict(list)
        for f in files:
            groups[f.parent].append(f.name)
        for parent in sorted(groups.keys(), key=lambda x: str(x)):
            lines.append(f"\U0001F4C1 {parent.name}/")
            for fname in sorted(groups[parent]):
                lines.append(f"    \U0001F4C4 {fname}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Construction des lignes de la hiérarchie de sortie
# ---------------------------------------------------------------------------

def build_hierarchy_lines(p: HierarchyParams):
    if not p.scanned_files:
        return [("No source selected.", None)]

    date_sort = p.date_sort
    preserve = p.preserve and p.source_is_folder
    factor = estimate_factor(p.fmt, p.quality, lossless=p.lossless)

    sources = p.source_paths[0] if p.source_is_folder else p.source_paths
    try:
        _, _, base = scan_sources(sources, recursive=p.recursive)
    except Exception:
        base = None

    if p.dest_mode == "same":
        effective_output = None
    elif p.dest_mode == "default":
        effective_output = p.default_output
    else:
        raw = p.custom_output.strip()
        effective_output = Path(raw) if raw else p.default_output

    if effective_output and p.package_subfolder:
        safe = "".join(c for c in p.package_subfolder if c not in r'<>:"/\|?*').strip()
        if safe:
            effective_output = effective_output / safe

    _multi_year = False
    if date_sort != "none":
        try:
            years = {datetime.fromtimestamp(f.stat().st_mtime).year
                     for f in p.scanned_files if f.exists()}
            _multi_year = len(years) > 1
        except Exception:
            pass
        if p.date_force_year:
            _multi_year = True

    folder_info = defaultdict(lambda: {"count": 0, "src_size": 0})
    date_dirs: set = set()

    for src in p.scanned_files:
        try:
            size = src.stat().st_size
        except Exception:
            size = 0
        if effective_output is None:
            dst_dir = src.parent
        else:
            date_sub = _date_subdir(src, date_sort, multi_year=_multi_year,
                                    day_style=p.date_day_style)
            date_placement = p.date_placement
            if preserve and base and src.is_relative_to(base):
                rel_dir = src.relative_to(base).parent
                if date_placement == "leaf":
                    dst_dir = effective_output / rel_dir / date_sub
                    _date_base = effective_output / rel_dir
                else:
                    dst_dir = effective_output / date_sub / rel_dir
                    _date_base = effective_output
            else:
                dst_dir = effective_output / date_sub
                _date_base = effective_output
            if date_sub.parts:
                _cur = _date_base
                for _part in date_sub.parts:
                    _cur = _cur / _part
                    date_dirs.add(_cur)
        folder_info[dst_dir]["count"] += 1
        folder_info[dst_dir]["src_size"] += size

    if not folder_info:
        return [("No files found.", None)]

    all_nodes: dict = {}
    for leaf, info in folder_info.items():
        est = int(info["src_size"] * factor)
        if leaf not in all_nodes:
            all_nodes[leaf] = {"count": 0, "est_size": 0}
        all_nodes[leaf]["count"] += info["count"]
        all_nodes[leaf]["est_size"] += est
        if effective_output:
            q = leaf.parent
            while q != q.parent:
                if q not in all_nodes:
                    all_nodes[q] = {"count": 0, "est_size": 0}
                all_nodes[q]["count"] += info["count"]
                all_nodes[q]["est_size"] += est
                if q == effective_output:
                    break
                q = q.parent

    for _d in date_dirs:
        if _d in all_nodes:
            all_nodes[_d]["is_date"] = True

    # Option A: no-workflow → no-workflow/ subfolder dans chaque dossier de sortie
    if p.sort_no_workflow and p.files_without_workflow and effective_output is not None:
        for src in p.files_without_workflow:
            try:
                size = src.stat().st_size
            except Exception:
                size = 0
            date_sub = _date_subdir(src, date_sort, multi_year=_multi_year,
                                    day_style=p.date_day_style)
            date_placement = p.date_placement
            if preserve and base and src.is_relative_to(base):
                rel_dir = src.relative_to(base).parent
                if date_placement == "leaf":
                    dst_dir = effective_output / rel_dir / date_sub
                else:
                    dst_dir = effective_output / date_sub / rel_dir
            else:
                dst_dir = effective_output / date_sub
            nwf_leaf = dst_dir / "no-workflow"
            est = int(size * factor)
            if nwf_leaf not in all_nodes:
                all_nodes[nwf_leaf] = {"count": 0, "est_size": 0, "is_nowf": True}
            all_nodes[nwf_leaf]["count"] += 1
            all_nodes[nwf_leaf]["est_size"] += est
            if dst_dir not in all_nodes:
                all_nodes[dst_dir] = {"count": 0, "est_size": 0}
            q = dst_dir.parent
            while q != q.parent:
                if q not in all_nodes:
                    all_nodes[q] = {"count": 0, "est_size": 0}
                if q == effective_output:
                    break
                q = q.parent

    # Fichiers non convertibles → résumé violet par dossier de destination
    copy_summaries: dict = {}
    if p.copy_unsupported and p.unsupported_files and effective_output is not None:
        copy_by_dir: dict = defaultdict(lambda: {"count": 0, "size": 0})
        for src in p.unsupported_files:
            try:
                size = src.stat().st_size
            except Exception:
                size = 0
            date_sub = _date_subdir(src, date_sort, multi_year=_multi_year,
                                    day_style=p.date_day_style)
            date_placement = p.date_placement
            if preserve and base and src.is_relative_to(base):
                rel_dir = src.relative_to(base).parent
                if date_placement == "leaf":
                    dst_dir = effective_output / rel_dir / date_sub
                else:
                    dst_dir = effective_output / date_sub / rel_dir
            else:
                dst_dir = effective_output / date_sub
            copy_by_dir[dst_dir]["count"] += 1
            copy_by_dir[dst_dir]["size"] += size
            if dst_dir not in all_nodes:
                all_nodes[dst_dir] = {"count": 0, "est_size": 0}
            q = dst_dir.parent
            while q != q.parent:
                if q not in all_nodes:
                    all_nodes[q] = {"count": 0, "est_size": 0}
                if q == effective_output:
                    break
                q = q.parent
        copy_summaries = dict(copy_by_dir)

    lines = []

    if effective_output:
        children: dict = defaultdict(list)
        for path in all_nodes:
            if path != effective_output:
                parent = path.parent
                if parent in all_nodes:
                    children[parent].append(path)
        render_tree_node(effective_output, children, all_nodes,
                         lines, "", True, True,
                         copy_summaries=copy_summaries)
    else:
        for path in sorted(all_nodes.keys(), key=lambda x: str(x)):
            node = all_nodes[path]
            lines.append((
                f"\U0001F4C1 {path}/   "
                f"{node['count']} file(s) · ~{human_size(node['est_size'])}",
                "hier_dir",
            ))

    total_count = sum(v["count"] for v in folder_info.values())
    total_est = int(sum(v["src_size"] for v in folder_info.values()) * factor)
    lines.append(("", None))
    lines.append((
        f"  Total: {total_count} file(s) · ~{human_size(total_est)} (estimated)",
        "hier_total",
    ))
    return lines

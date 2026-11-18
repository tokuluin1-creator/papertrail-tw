"""Draw manuscript figures only from supplied records and project design."""
import os
from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


INK, TEAL, LIGHT = "#172d34", "#116b69", "#d6e2e1"


@dataclass(frozen=True)
class Figure:
    stem: str
    section: str
    title: str
    source: str


def configure_font():
    custom = os.environ.get("PAPERTRAIL_FONT")
    if custom:
        if not Path(custom).is_file():
            raise ValueError("PAPERTRAIL_FONT 指定的字型檔不存在")
        font_manager.fontManager.addfont(custom)
        family = font_manager.FontProperties(fname=custom).get_name()
    else:
        available = set(font_manager.fontManager.get_font_names())
        choices = ("Microsoft JhengHei", "PingFang TC", "Noto Sans CJK TC", "Source Han Sans TW",
                   "Noto Sans TC", "Heiti TC", "Noto Sans CJK JP", "Arial Unicode MS")
        family = next((f for f in choices if f in available), None)
        if not family:
            raise ValueError("繪圖需要中文字型。請安裝 Noto Sans CJK TC，或以 PAPERTRAIL_FONT 指定 .otf 或 .ttf")
    plt.rcParams.update({"font.family": family, "font.size": 10, "text.color": INK,
                         "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
                         "pdf.fonttype": 3, "axes.unicode_minus": False})


def multiline(text, columns):
    return "\n".join(wrap(text, width=columns, break_long_words=True, break_on_hyphens=False)) or text


def save(fig, directory, stem):
    fig.savefig(directory / (stem + ".pdf"), bbox_inches="tight", pad_inches=.10)
    fig.savefig(directory / (stem + ".png"), bbox_inches="tight", pad_inches=.10, dpi=210)
    plt.close(fig)


def concept_figure(project, groups, target, stem):
    if groups:
        left, middle, right = project.group_label, [m.group for m in groups], project.metric + "（" + project.unit + "）"
        title = "比較條件與觀察指標"
        src = "project.json 與 measurements.csv。箭線連結比較條件及觀察指標。"
    else:
        left, right = "研究問題", "可回查的正文段落"
        present = {s.kind for s in project.sources.values()}
        middle = [s for k, s in [("note", "研究筆記"), ("reference", "已讀文獻")] if k in present]
        title = "研究問題與寫作材料"
        src = "依本研究登錄的筆記與書目類型繪製。箭線表示資料用途。"
    mid = len(middle)
    height = max(1.65, .68 * mid + .55)
    fig, ax = plt.subplots(figsize=(7.0, height))
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    positions = [.5] if mid == 1 else [.83 - i * .66 / (mid-1) for i in range(mid)]
    def box(x, y, label, width, accent=False):
        label = multiline(label, 10)
        half = max(.22, .12 * (label.count("\n") + 1)) / height
        p = FancyBboxPatch((x-width/2, y-half), width, 2*half,
                           boxstyle="round,pad=0.012,rounding_size=0.018",
                           edgecolor=TEAL if accent else "#9aafaf", linewidth=1.0,
                           facecolor="#e6f2ef" if accent else "white")
        ax.add_patch(p)
        ax.text(x, y, label, ha="center", va="center", fontsize=10, linespacing=1.12)
    def arrow(x, y, x2, y2):
        ax.add_patch(FancyArrowPatch((x, y), (x2, y2), arrowstyle="-|>", mutation_scale=11,
                                     color="#62817f", linewidth=1.0, shrinkA=1, shrinkB=1))
    for y, label in zip(positions, middle):
        arrow(.239, .5, .366, y)
        arrow(.633, y, .758, .5)
        box(.5, y, label, .23, True)
    box(.12, .5, left, .21)
    box(.88, .5, right, .21)
    save(fig, target, stem)
    return Figure(stem, "methods", title, src)


def value_figure(project, groups, target, stem):
    fig, ax = plt.subplots(figsize=(7.0, max(1.75, .52*len(groups)+.78)), layout="constrained")
    for y, m in enumerate(groups):
        ax.scatter(m.values, [y]*len(m.values), s=28, facecolors="white", edgecolors="#577371",
                   linewidths=1, zorder=2)
        ax.scatter([m.average], [y], marker="D", s=56, color=TEAL, zorder=3)
    ax.set_yticks(range(len(groups)), [f"{multiline(m.group, 14)}（n = {len(m.values)}）" for m in groups])
    ax.set_ylim(len(groups)-.48, -.48)
    ax.set_xlabel(f"{project.metric}（{project.unit}）")
    if all(v >= 0 for m in groups for v in m.values):
        ax.set_xlim(left=0)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(LIGHT)
    ax.tick_params(axis="both", length=0, pad=5)
    ax.grid(axis="x", color=LIGHT, linewidth=.65, zorder=0)
    save(fig, target, stem)
    return Figure(stem, "results", f"各組{project.metric}的分布",
                  "measurements.csv。圓點代表單筆紀錄，菱形代表各組平均。")


def draw_figures(project, target):
    target.mkdir()
    configure_font()
    pages = [project.measures[i:i+5] for i in range(0, len(project.measures), 5)] or [[]]
    concepts, measures = [], []
    for j, subset in enumerate(pages, 1):
        suffix = "" if len(pages) == 1 else f"-{j}"
        concepts.append(concept_figure(project, subset, target, "concept" + suffix))
        if subset:
            measures.append(value_figure(project, subset, target, "values" + suffix))
    return concepts + measures

"""
Render the daily metrics as a dark-themed dashboard PNG (stat cards + charts) for posting
to Discord as an image attachment. Pure matplotlib; no display needed (Agg backend).
"""
from pathlib import Path

BG = "#0e1117"
CARD = "#1b2233"
FG = "#eef1f6"
SUB = "#9aa4b2"
GRID = "#2a3142"
C = ["#5865F2", "#2ecc71", "#f1c40f", "#e84393", "#00b8d4", "#ff7043"]


def render(stats: dict, out_path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = stats["totals"]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(12, 7), dpi=110, facecolor=BG)
    fig.text(0.035, 0.935, "VideoPOsting — Daily Dashboard", fontsize=24, fontweight="bold", color=FG)
    fig.text(0.035, 0.89, stats.get("when", ""), fontsize=12, color=SUB)

    # Stat cards
    cards = [("VIEWS", t["views"], C[0]), ("LIKES", t["likes"], C[1]),
             ("COMMENTS", t["comments"], C[2]), ("SHORTS", t["count"], C[3])]
    for i, (label, val, color) in enumerate(cards):
        ax = fig.add_axes([0.035 + i * 0.238, 0.70, 0.218, 0.14])
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, color=CARD))
        ax.text(0.07, 0.62, f"{val:,}", fontsize=25, fontweight="bold", color=color, va="center")
        ax.text(0.07, 0.24, label, fontsize=11, color=SUB, va="center")

    def style(ax):
        ax.set_facecolor(BG)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0, colors=SUB)
        ax.grid(axis="x", color=GRID, lw=0.7)
        ax.set_axisbelow(True)

    # Top Shorts by views (left)
    top = stats["top"][:6][::-1]
    ax1 = fig.add_axes([0.26, 0.09, 0.33, 0.52])
    style(ax1)
    if top:
        labels = [(r["title"][:24] + "…") if len(r["title"]) > 24 else r["title"] for r in top]
        ax1.barh(range(len(top)), [r["views"] for r in top], color=C[0], height=0.62)
        ax1.set_yticks(range(len(top)))
        ax1.set_yticklabels(labels, fontsize=9, color=FG)
    ax1.set_title("Top Shorts by views", color=FG, loc="left", fontweight="bold", pad=12)

    # Avg views by creator (right top)
    bc = sorted(stats["by_creator"].items(), key=lambda x: -x[1])[:5]
    ax2 = fig.add_axes([0.66, 0.385, 0.30, 0.225])
    style(ax2)
    ax2.grid(axis="x", lw=0)
    ax2.grid(axis="y", color=GRID, lw=0.7)
    if bc:
        ax2.bar(range(len(bc)), [v for _, v in bc], color=C[4], width=0.62)
        ax2.set_xticks(range(len(bc)))
        ax2.set_xticklabels([k[:9] for k, _ in bc], fontsize=8, color=FG)
    ax2.set_title("Avg views by creator", color=FG, loc="left", fontweight="bold", pad=10)

    # Narrated vs raw (right bottom)
    bf = {k: v for k, v in stats["by_format"].items() if v is not None}
    ax3 = fig.add_axes([0.66, 0.09, 0.30, 0.205])
    style(ax3)
    ax3.grid(axis="x", lw=0)
    ax3.grid(axis="y", color=GRID, lw=0.7)
    if bf:
        keys = list(bf.keys())
        ax3.bar(range(len(keys)), [bf[k] for k in keys], color=[C[1], C[3]][:len(keys)], width=0.5)
        ax3.set_xticks(range(len(keys)))
        ax3.set_xticklabels(keys, fontsize=10, color=FG)
    ax3.set_title("Avg views: narrated vs raw", color=FG, loc="left", fontweight="bold", pad=10)

    fig.savefig(out_path, facecolor=BG)
    plt.close(fig)
    return out_path

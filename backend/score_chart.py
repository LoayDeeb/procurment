import matplotlib.pyplot as plt
import io
import base64
import numpy as np

def render_score_chart(scores: dict, output_path: str):
    categories = list(scores.keys())
    values = list(scores.values())
    fig, ax = plt.subplots(figsize=(6, 3))
    modern_colors = ['#1976D2', '#26A69A', '#FFD600', '#43A047', '#8E24AA']
    bars = ax.bar(categories, values, color=modern_colors)
    ax.set_ylim(0, 20)
    ax.set_ylabel('Score (0-20)', fontsize=12, fontweight='bold')
    ax.set_title('Score Breakdown', fontsize=14, fontweight='bold')
    ax.set_xlabel('')
    ax.tick_params(axis='x', labelsize=12)
    ax.tick_params(axis='y', labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, yval + 0.5, f'{int(yval)}', ha='center', va='bottom', fontsize=11, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_path, format='png')
    plt.close(fig)

# For embedding in HTML as base64

def render_score_chart_base64(scores: dict) -> str:
    categories = list(scores.keys())
    values = list(scores.values())
    fig, ax = plt.subplots(figsize=(6, 3))
    modern_colors = ['#1976D2', '#26A69A', '#FFD600', '#43A047', '#8E24AA']
    bars = ax.bar(categories, values, color=modern_colors)
    ax.set_ylim(0, 20)
    ax.set_ylabel('Score (0-20)', fontsize=12, fontweight='bold')
    ax.set_title('Score Breakdown', fontsize=14, fontweight='bold')
    ax.set_xlabel('')
    ax.tick_params(axis='x', labelsize=12)
    ax.tick_params(axis='y', labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, yval + 0.5, f'{int(yval)}', ha='center', va='bottom', fontsize=11, fontweight='bold')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode('utf-8')
    return f'data:image/png;base64,{img_b64}'


def render_score_dashboard_base64(scores: dict, overall_score: float) -> str:
    categories = list(scores.keys())
    values = [float(scores.get(k, 0) or 0) for k in categories]

    fig = plt.figure(figsize=(10.5, 4.6), dpi=140, constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.75, 1], wspace=0.28)
    fig.patch.set_facecolor("#ffffff")

    # Left: horizontal score bars with normalized % labels
    ax1 = fig.add_subplot(gs[0, 0])
    y = np.arange(len(categories))
    colors = ["#1a4fb5", "#2a7de1", "#11a37f", "#f1a208", "#7a4dd8"]
    bars = ax1.barh(y, values, color=colors, edgecolor="#e8eef8", height=0.58)
    ax1.set_yticks(y)
    ax1.set_yticklabels(categories, fontsize=10)
    ax1.invert_yaxis()
    ax1.set_xlim(0, 20)
    ax1.set_xlabel("Score out of 20", fontsize=9, color="#4a5b82")
    ax1.grid(axis="x", alpha=0.22, linestyle="--")
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.spines["left"].set_color("#d4ddf0")
    ax1.spines["bottom"].set_color("#d4ddf0")
    ax1.set_title("Technical Evaluation Breakdown", fontsize=12, fontweight="bold", color="#1f3280", pad=10)
    for idx, bar in enumerate(bars):
        val = values[idx]
        pct = int(round((val / 20) * 100))
        ax1.text(
            min(val + 0.45, 19.2),
            bar.get_y() + bar.get_height() / 2,
            f"{int(val)}/20 ({pct}%)",
            va="center",
            fontsize=9,
            color="#2d3b62",
            fontweight="semibold",
        )

    # Right: donut for overall score
    ax2 = fig.add_subplot(gs[0, 1])
    overall = max(0.0, min(100.0, float(overall_score or 0)))
    rest = max(0.0, 100.0 - overall)
    ax2.pie(
        [overall, rest],
        colors=["#1f6feb", "#e8edf8"],
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.28, "edgecolor": "white"},
    )
    ax2.text(0, 0.05, f"{int(round(overall))}", ha="center", va="center", fontsize=28, color="#1f3280", fontweight="bold")
    ax2.text(0, -0.2, "Overall Score", ha="center", va="center", fontsize=10, color="#62739c")
    ax2.set_title("Overall Performance", fontsize=12, fontweight="bold", color="#1f3280", pad=10)
    ax2.set_aspect("equal")

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/png;base64,{img_b64}"

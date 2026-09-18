"""从阶段0抽取的Matplotlib绘图原语，不执行数据集读写。"""
import os
os.environ.setdefault("MPLCONFIGDIR", "/tmp/semantic-pallet-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
COLORS = {"normal": "#78909c", "heavy": "#355c9a", "fragile": "#ef8a32", "electronics": "#31a9b8", "fragile_electronics": "#8e63b0"}
def color_for(item):
    if item.get("fragile") and item.get("product_category") == "electronics":
        return COLORS["fragile_electronics"]
    if item.get("fragile"):
        return COLORS["fragile"]
    if item.get("product_category") == "electronics":
        return COLORS["electronics"]
    if item.get("weight_class") == "heavy":
        return COLORS["heavy"]
    return COLORS["normal"]

def draw_box(ax, record, color, alpha=0.85, edge="black", label=None):
    x, y, z = record["pose"]["x_mm"], record["pose"]["y_mm"], record["pose"]["z_base_mm"]
    length, width, height = record["oriented_size_mm"]
    ax.bar3d(x - length / 2, y - width / 2, z, length, width, height, color=color, alpha=alpha, edgecolor=edge, linewidth=0.45, shade=True)
    if label:
        ax.text(x, y, z + height + 12, label, ha="center", va="bottom", fontsize=6, color="#222222")

def setup_pallet(ax, container, title=None):
    length, width, height = container["length_mm"], container["width_mm"], container["max_height_mm"]
    ax.set_xlim(-length / 2, length / 2)
    ax.set_ylim(-width / 2, width / 2)
    ax.set_zlim(0, height)
    ax.set_box_aspect((length, width, height))
    ax.view_init(elev=25, azim=-55)
    ax.set_xlabel("X / mm", fontsize=7)
    ax.set_ylabel("Y / mm", fontsize=7)
    ax.set_zlabel("Z / mm", fontsize=7)
    ax.tick_params(labelsize=6)
    if title:
        ax.set_title(title, fontsize=9)

def draw_pallet(ax, container, placed, candidate=None, candidate_label=None):
    setup_pallet(ax, container)
    for item in placed:
        draw_box(ax, item, color_for(item), label=item["item_id"])
    if candidate:
        draw_box(ax, candidate, "#ffd54f", alpha=0.48, edge="#d32f2f", label=candidate_label)

def render_workspace(case, scenario, output):
    fig = plt.figure(figsize=(14, 7), dpi=110)
    supply = fig.add_subplot(1, 2, 1, projection="3d")
    pallet = fig.add_subplot(1, 2, 2, projection="3d")
    available = case["available_items"]
    max_dim = max(max(x["dimensions_mm"].values()) for x in available)
    supply.set_xlim(-max_dim, max_dim)
    supply.set_ylim(-max_dim, max_dim)
    supply.set_zlim(0, max_dim * 1.5)
    supply.set_box_aspect((1, 1, 1))
    supply.view_init(elev=25, azim=-55)
    supply.set_title("PICK / BUFFER AREA", fontsize=11)
    for index, item in enumerate(available):
        length, width, height = (item["dimensions_mm"][k] for k in ("length", "width", "height"))
        view = {"pose": {"x_mm": 0, "y_mm": index * (width + 20), "z_base_mm": 0}, "oriented_size_mm": [length, width, height]}
        flags = "/".join(x for x, yes in (("H", item["weight_class"] == "heavy"), ("F", item["fragile"]), ("E", item["product_category"] == "electronics"), ("NS", not item["stackable"])) if yes) or "general"
        draw_box(supply, view, color_for(item), label=f"{item['item_id']}  {flags}\n{length}x{width}x{height}  {item['mass_kg']:.2f}kg")
    draw_pallet(pallet, scenario["container"], case["placed_items"])
    pallet.set_title(f"PALLET STATE | {case['decision_case_id']} | step {case['step_index']}", fontsize=11)
    fig.suptitle("Synthetic palletizing observation (dataset ground truth)", fontsize=13)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)

def render_selected_result(case, scenario, candidate, output):
    """渲染当前取料箱体和执行候选后的预期码垛结果。"""
    fig = plt.figure(figsize=(10, 7), dpi=110)
    ax = fig.add_subplot(1, 1, 1, projection="3d")
    draw_pallet(ax, scenario["container"], case["placed_items"])
    draw_box(ax, candidate, "#62b66e", alpha=0.88, edge="#146b2a", label="SELECTED")
    ax.set_title(f"SELECTED RESULT | {case['decision_case_id']} | {candidate['candidate_id']}", fontsize=11)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)

def render_final_layout(container, placed_items, title, output):
    fig = plt.figure(figsize=(10, 7), dpi=110)
    ax = fig.add_subplot(1, 1, 1, projection="3d")
    draw_pallet(ax, container, placed_items)
    ax.set_title(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)

def render_montage(case, scenario, cset, output):
    candidates = cset["candidates"]
    cols = 4
    rows = (len(candidates) + cols - 1) // cols
    fig = plt.figure(figsize=(14, max(3.2 * rows, 4)), dpi=100)
    for index, candidate in enumerate(candidates, 1):
        ax = fig.add_subplot(rows, cols, index, projection="3d")
        draw_pallet(ax, scenario["container"], case["placed_items"], candidate, f"C{index:02d}")
        pose = candidate["pose"]
        label = candidate.get("display_label", f"C{index:02d}")
        # 阶段1C图像有意隐藏内部候选ID和原始排序。
        ax.set_title(f"{label}\n({pose['x_mm']:.0f}, {pose['y_mm']:.0f}, z={pose['z_base_mm']:.0f}) yaw={pose['yaw_deg']}", fontsize=7)
        ax.set_xlabel(""); ax.set_ylabel(""); ax.set_zlabel("")
    fig.suptitle(f"VALID PLACEMENT CANDIDATES | {case['decision_case_id']}", fontsize=12)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)

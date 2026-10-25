"""Export the real Text improvement case and matrix as a shareable figure."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

HERE = Path(__file__).resolve().parent
FONT = FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family': FONT.get_name(), 'axes.unicode_minus': False,
                     'font.size': 10, 'figure.facecolor': '#f1f5f9'})
DATA = json.loads((HERE / 'data.json').read_text())
METHODS = ['single_greedy', 'buffer_fifo', 'buffer_heuristic', 'buffer_search']
NAMES = ['单箱贪心', '缓冲 FIFO', '缓冲启发式', '缓冲搜索']
COLORS = {'food': '#eab967', 'household_cleaner': '#bd92d5',
          'glassware': '#66bcbc', 'general': '#85a9ca', 'electronics': '#df8f8f'}


def faces(box):
    p = box['pose']
    length, width, height = box['oriented_size_mm']
    x, y, z = p['x_mm'] - length / 2, p['y_mm'] - width / 2, p['z_base_mm']
    points = [(x, y, z), (x + length, y, z), (x + length, y + width, z),
              (x, y + width, z), (x, y, z + height), (x + length, y, z + height),
              (x + length, y + width, z + height), (x, y + width, z + height)]
    return [[points[i] for i in indices] for indices in
            [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]]


def main():
    fig = plt.figure(figsize=(18, 12))
    fig.text(.04, .956, 'O4-D 真实缓冲实验｜同一订单，从 9/19 到 19/19 箱', fontsize=23, weight='bold', color='#173650')
    fig.text(.04, .921, '案例 O4_ORDER_02_2 · Flash Text 真实记录 · Image / Parser / Oracle 同样重现此件数结果', fontsize=13, color='#536b80')
    fig.legend(handles=[Patch(facecolor=COLORS[key], label=label) for key, label in
                        [('food', '食品'), ('household_cleaner', '清洁用品'),
                         ('glassware', '玻璃制品'), ('general', '普通货物'),
                         ('electronics', '电子产品')]],
               loc='upper left', bbox_to_anchor=(.035, .905), ncol=5, frameon=False, fontsize=10)
    for index, method in enumerate(METHODS):
        ep = next(e for e in DATA['episodes'] if e['task'] == 'O4_ORDER_02_2'
                  and e['backend'] == 'remote_text' and e['planner'] == method)
        ax = fig.add_axes([.025 + index * .245, .48, .24, .38], projection='3d')
        for box in ep['frames'][-1]['placed']:
            ax.add_collection3d(Poly3DCollection(faces(box), facecolor=COLORS.get(box['cargo_category'], '#aaa'),
                                               edgecolor='white', linewidth=.5, alpha=.96))
            p = box['pose']
            ax.text(p['x_mm'], p['y_mm'], p['z_base_mm'] + box['oriented_size_mm'][2] + 5,
                    box['object_id'].replace('item_', ''), fontsize=6, ha='center')
        ax.set(xlim=(-600, 600), ylim=(-500, 500), zlim=(0, 850))
        ax.set_box_aspect((1200, 1000, 850))
        ax.view_init(elev=27, azim=-58)
        ax.set_xlabel('X / mm', labelpad=0)
        ax.set_ylabel('Y / mm', labelpad=0)
        ax.tick_params(labelsize=6, pad=0)
        ax.set_title(f'{NAMES[index]} · {ep["summary"]["placed_items"]}/19 箱', fontsize=14, color='#075985', pad=5)
        x = .04 + index * .245
        seq = [v.replace('item_', '') for v in ep['sequence']]
        lines = [' → '.join(seq[n:n + 7]) for n in range(0, len(seq), 7)]
        fig.text(x, .467, '实际码放箱号：\n' + '\n'.join(lines), fontsize=9, va='top', color='#334e68')
        reasons = ['物理候选耗尽', 'FIFO 队首受阻', '全部放完', '全部放完']
        fig.text(x, .366, f'容量 {1 if index == 0 else 3} · {reasons[index]}', fontsize=11, color='#075985')
    ax = fig.add_axes([.07, .105, .48, .19])
    for j, (backend, label, color) in enumerate([
            ('oracle_ast', 'Parser / Oracle', '#366a92'),
            ('remote_text', 'Flash Text', '#22a4a4'),
            ('remote_image', 'Flash Image', '#c49a48')]):
        vals = [next(r['clean'] for r in DATA['overview'] if r['backend'] == backend and r['planner'] == m)
                for m in METHODS]
        xs = [i + (j - 1) * .24 for i in range(4)]
        ax.bar(xs, vals, width=.22, color=color, label=label)
        for x, value in zip(xs, vals):
            ax.text(x, value + .3, str(value), ha='center', fontsize=9)
    ax.set_xticks(range(4), NAMES)
    ax.set_ylim(0, 21)
    ax.set_ylabel('无违规完成订单数 / 72')
    ax.set_title('完整开发矩阵：启发式本轮优于搜索', loc='left', fontsize=13)
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(loc='upper right', fontsize=8)
    fig.text(.61, .285, '进展与边界', fontsize=16, weight='bold', color='#173650')
    fig.text(.61, .245,
             '• 1152/1152 个订单 episode；真实 API 尝试 4472 次。\n'
             '• 当前支持软预算＋几何选址、三箱缓冲及有界搜索。\n'
             '• 576 个模型 episode 中 243 个因协议错误停止。\n'
             '• O3 完整“预算＋布局”评分尚未迁移至缓冲模式。\n'
             '• 144 条真实配对固定题待补；未见泛化尚未测量。',
             fontsize=12, linespacing=1.9, va='top', color='#334e68')
    fig.text(.04, .035, '选择规则：本例为 Oracle 搜索相对单箱件数增量最大案例；用于解释机制，不代表平均收益。所有绘图使用原始已提交位置，无新增调用或布局补全。',
             fontsize=10, color='#61758b')
    fig.savefig(HERE / 'overview.png', dpi=150)
    fig.savefig(HERE / 'overview.pdf')
    print('Exported overview.png and overview.pdf')


if __name__ == '__main__':
    main()

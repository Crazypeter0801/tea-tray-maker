#!/usr/bin/env python3
"""筋宽 ↔ 挤出线：预测一条等宽直筋里会排几根料、正中会不会多出一根「补缝线」。

背景（v4i 实测）：2.2 mm 筋在 0.12 层高、外墙 0.42 / 内墙 0.45 时被切成
0.420 / 0.450 / 0.563 / 0.450 / 0.420 —— 正中那根被 slicer 撑宽 25%，
两侧接缝在实物上就是筋顶中间那条细线 / 被带起的中线。改墙圈数、infill_wall_overlap、
内部实心线宽都不改变这个结果；只有让「筋宽 ≈ 整数根料」才消失。

模型（与 Bambu Studio 的线距公式一致）：
    相邻两根料的重叠 k = 层高 × (1 − π/4)
    N 根料恰好铺满的宽度 nominal(N) = 2·外墙线宽 + (N−2)·内墙线宽 − (N−1)·k
    实际筋宽 W 落在 nominal(N) 与 nominal(N+1) 之间时，多出的 e = W − nominal(N)
    全部摊给正中的料：N 为奇数 → 1 根变宽 e；N 为偶数 → 2 根各变宽 e/2。

用 v4i/v4j/v4k 三组切片校准（误差 < 0.002 mm）：
    W=2.20 → 中线 0.563；W=2.58 → 中间两根 0.484；W=1.70 → 中间两根 0.469。

适用范围：底座/筋全实心或 Arachne 墙把筋填满的情况；筋里还有稀疏填充时不适用
（例如 2 圈墙 + 99% 稀疏，正中是一根 0.400 的稀疏线、旁边留空）。结论只是预测，
最终以切片预览里该处的线条类型和线宽为准。

用法：
    python rib_width.py --check 2.2 --check 3.8            # 默认 0.12 层高
    python rib_width.py --layer 0.2 --check 2.2 --suggest
"""
import argparse
import json
import math

TOL = 0.08   # 中间料最多被撑宽 8% 视为可接受（v4k +7.5%、v4j +4.2% 实测无中缝）


def overlap(layer):
    return layer * (1 - math.pi / 4)


def nominal(n, outer, inner, layer):
    if n < 2:
        raise ValueError('至少 2 根料')
    return 2 * outer + (n - 2) * inner - (n - 1) * overlap(layer)


def predict(width, outer=0.42, inner=0.45, layer=0.12):
    n = 2
    while nominal(n + 1, outer, inner, layer) <= width + 1e-9:
        n += 1
    base = nominal(n, outer, inner, layer)
    if width < base - 1e-9:
        return dict(width=width, strands=None, verdict='太窄：放不下两根外墙')
    e = width - base
    if n == 2:
        lines = [outer + e / 2, outer + e / 2]
        middle = []
    elif n % 2:
        lines = [outer] + [inner] * ((n - 3) // 2) + [inner + e] + [inner] * ((n - 3) // 2) + [outer]
        middle = [inner + e]
    else:
        k = (n - 4) // 2
        lines = [outer] + [inner] * k + [inner + e / 2] * 2 + [inner] * k + [outer]
        middle = [inner + e / 2] * 2
    grow = (max(middle) / inner - 1) if middle else e / 2 / outer
    nxt = nominal(n + 1, outer, inner, layer)
    verdict = ('OK：接近整数根料' if grow <= TOL else
               f'不推荐：正中料被撑宽 {grow:.0%}，筋顶中间容易出现接缝/细线')
    return dict(width=width, layer=layer, strands=n, lines_mm=[round(v, 3) for v in lines],
                middle_growth_pct=round(100 * grow, 1), verdict=verdict,
                nearest_good_mm=[round(base, 3), round(nxt, 3)])


def suggest(outer, inner, layer, lo=1.2, hi=4.5):
    out = []
    n = 3
    while True:
        base = nominal(n, outer, inner, layer)
        if base > hi:
            break
        if base >= lo:
            span = 2 * TOL * inner if n % 2 == 0 else TOL * inner
            out.append(dict(strands=n, ideal_mm=round(base, 3),
                            ok_range_mm=[round(base, 3), round(base + span, 3)]))
        n += 1
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--check', type=float, action='append', default=[], help='要检查的筋/围边宽度 mm')
    p.add_argument('--layer', type=float, default=0.12, help='层高 mm')
    p.add_argument('--outer', type=float, default=0.42, help='外墙线宽 mm（Bambu 0.4 喷嘴默认 0.42）')
    p.add_argument('--inner', type=float, default=0.45, help='内墙线宽 mm（Bambu 0.4 喷嘴默认 0.45）')
    p.add_argument('--suggest', action='store_true', help='列出该层高下推荐的筋宽')
    a = p.parse_args()
    res = dict(checks=[predict(w, a.outer, a.inner, a.layer) for w in a.check])
    if a.suggest or not a.check:
        res['suggest'] = suggest(a.outer, a.inner, a.layer)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""杯子放在茶盘上稳不稳：在真实 STL 上逐点检查杯脚落在筋顶的情况，输出热力图与 JSON。

方法（与图案无关，波纹、字母、猫咪线稿都适用）：
1. 找承杯面：盘内最高、且面积足够大的水平面（筋顶）。`--crown-z` 可手动指定。
2. 把承杯面三角形投影成 0.1 mm 栅格（support）；比承杯面更高的部分（围边）作为障碍。
3. 在盘内按网格放杯子中心，对每个杯脚采样：
   - 圈足（默认）：杯脚是直径 D 的细圆环，只看环线上哪些角度压在筋顶上；
   - 平底（--flat）：杯脚是直径 D 的实心圆，看圆内哪些点压在筋顶上。
4. 指标：
   - contact_pct：杯脚落在筋顶上的比例；
   - max_gap_deg：绕杯心一圈最长的「下面没有筋」的连续角度；
   - one_sided：所有支撑点都挤在半圈以内（max_gap ≥ 180°），重心不在支撑范围内，
     放上去会往空的一侧歪。这是纯几何判据，不含摩擦、杯重分布和打印误差。

用法：
    python cup_stability.py tray.stl --out-dir out --foot 30
    python cup_stability.py tray.stl --out-dir out --foot 30 --foot 45:flat --at 60,90 --at 180,60

依赖：trimesh numpy pillow matplotlib。
"""
import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

RES = 0.1          # 栅格分辨率 mm
ANG_STEP = 0.5     # 圈足角度采样 deg


def horizontal_planes(mesh, tol=0.02):
    """所有朝上的水平面，按高度聚合面积。"""
    up = mesh.face_normals[:, 2] > 0.999
    z = mesh.triangles_center[up, 2]
    area = mesh.area_faces[up]
    key = np.round(z / tol) * tol
    planes = {}
    for k, a in zip(key, area):
        planes[float(k)] = planes.get(float(k), 0.0) + float(a)
    return dict(sorted(planes.items()))


def detect_crown(mesh, min_share=0.10):
    """承杯面 = 低于最高面、面积占外形投影 ≥ min_share 的水平面中最高的一个。"""
    planes = horizontal_planes(mesh)
    ext = mesh.extents
    footprint = ext[0] * ext[1]
    top = max(planes)
    cands = [z for z, a in planes.items() if z < top - 0.05 and a >= min_share * footprint]
    if not cands:
        raise SystemExit('找不到承杯面，请用 --crown-z 指定筋顶高度；水平面统计：'
                         + json.dumps({f'{k:.2f}': round(v) for k, v in planes.items()}))
    return max(cands), planes


class Raster:
    def __init__(self, bounds):
        (self.x0, self.y0), (x1, y1) = bounds[0][:2], bounds[1][:2]
        self.w = int(np.ceil((x1 - self.x0) / RES)) + 2
        self.h = int(np.ceil((y1 - self.y0) / RES)) + 2

    def draw(self, tris):
        img = Image.new('1', (self.w, self.h), 0)
        d = ImageDraw.Draw(img)
        for t in tris:
            d.polygon([((p[0] - self.x0) / RES, (p[1] - self.y0) / RES) for p in t], fill=1)
        return np.array(img, dtype=bool)

    def lookup(self, mask, x, y):
        i = np.clip(np.round((y - self.y0) / RES).astype(int), 0, self.h - 1)
        j = np.clip(np.round((x - self.x0) / RES).astype(int), 0, self.w - 1)
        return mask[i, j]


def max_gap_deg(hit, step):
    """每行一个圆周的布尔采样，返回最长连续 False 的角度。全 False → 360。"""
    n = hit.shape[1]
    out = np.full(hit.shape[0], 360.0)
    for r, row in enumerate(hit):
        if not row.any():
            continue
        k = int(np.argmax(row))                     # 从一个支撑点开始转一圈
        rolled = np.roll(row, -k)
        idx = np.flatnonzero(rolled)
        gaps = np.diff(np.concatenate([idx, [n + idx[0]]])) - 1
        out[r] = gaps.max() * step
    return out


def foot_samples(diameter, flat):
    ang = np.deg2rad(np.arange(0, 360, ANG_STEP))
    if not flat:
        return ang, np.full_like(ang, diameter / 2)
    radii = np.arange(1.0, diameter / 2 + 1e-9, 0.5)
    a, r = np.meshgrid(ang, radii)
    return a.ravel(), r.ravel()


def analyse(rs, support, blocked, inside, centres, diameter, flat):
    ang, rad = foot_samples(diameter, flat)
    dx, dy = rad * np.cos(ang), rad * np.sin(ang)
    # 杯脚外缘不能压到围边/超出盘面
    edge_a = np.deg2rad(np.arange(0, 360, 2.0))
    ex, ey = diameter / 2 * np.cos(edge_a), diameter / 2 * np.sin(edge_a)
    res = {k: np.full(len(centres), np.nan) for k in ('contact', 'gap')}
    valid = np.zeros(len(centres), bool)
    bins = np.round(np.rad2deg(ang) / ANG_STEP).astype(int) % int(360 / ANG_STEP)
    for s in range(0, len(centres), 256):
        c = centres[s:s + 256]
        X, Y = c[:, :1] + ex, c[:, 1:] + ey
        ok = rs.lookup(inside, X, Y).all(1) & ~rs.lookup(blocked, X, Y).any(1)
        if flat:
            # 实心杯底：整个圆面都不能压到围边
            DX, DY = c[:, :1] + dx, c[:, 1:] + dy
            ok &= ~rs.lookup(blocked, DX, DY).any(1)
        hit = rs.lookup(support, c[:, :1] + dx, c[:, 1:] + dy)
        res['contact'][s:s + 256] = hit.mean(1) * 100
        if flat:   # 按角度汇总：某个方向上只要有一点压着筋就算这一方向有支撑
            per_dir = np.zeros((len(c), int(360 / ANG_STEP)), bool)
            for b in np.unique(bins):
                per_dir[:, b] = hit[:, bins == b].any(1)
            hit = per_dir
        res['gap'][s:s + 256] = max_gap_deg(hit, ANG_STEP)
        valid[s:s + 256] = ok
    res['contact'][~valid] = np.nan
    res['gap'][~valid] = np.nan
    return res, valid


def summarise(res, valid, diameter, flat):
    c, g = res['contact'][valid], res['gap'][valid]
    one = g >= 180
    area = np.pi * (diameter / 2) ** 2
    out = dict(foot=f'{diameter:g}mm {"平底" if flat else "圈足"}', samples=int(valid.sum()),
               one_sided_count=int(one.sum()), one_sided_pct=round(100 * one.mean(), 2),
               no_contact_count=int((g >= 360).sum()),
               contact_median_pct=round(float(np.median(c)), 1),
               contact_p10_pct=round(float(np.percentile(c, 10)), 1),
               max_gap_median_deg=round(float(np.median(g)), 1),
               max_gap_p90_deg=round(float(np.percentile(g, 90)), 1))
    if flat:
        out['contact_area_median_mm2'] = round(float(np.median(c)) / 100 * area)
    return out


def render(path, rs, support, xs, ys, results, crown_z, title, share):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Hiragino Sans GB', 'Noto Sans CJK SC',
                                       'Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    n = len(results) + 1
    w_mm = rs.w * RES
    h_mm = rs.h * RES
    fig, axes = plt.subplots(n, 1, figsize=(9, n * (8.2 * h_mm / w_mm + 0.75) + 0.5),
                             layout='constrained')
    axes = np.atleast_1d(axes)
    ext = [rs.x0, rs.x0 + w_mm, rs.y0, rs.y0 + h_mm]
    axes[0].imshow(support, origin='lower', extent=ext, cmap='Blues', vmin=0, vmax=1.6)
    axes[0].set_title(f'承杯面（筋顶 z={crown_z:.2f}）· 深色 = 杯子能压到的地方，'
                      f'占盘面投影 {share:.1f}%', fontsize=11, loc='left')
    cmap = LinearSegmentedColormap.from_list('rb', ['#b2182b', '#f4a582', '#f7f7f7',
                                                     '#92c5de', '#2166ac'])
    cmap.set_bad('#e6e6e6')
    vmax = max(10.0, max(float(np.nanpercentile(r['contact'], 98)) for _, r, _ in results))
    for ax, (label, res, summ) in zip(axes[1:], results):
        grid = res['contact'].reshape(len(ys), len(xs))
        gap = res['gap'].reshape(len(ys), len(xs))
        im = ax.imshow(np.ma.masked_invalid(grid), origin='lower', cmap=cmap, vmin=0, vmax=vmax,
                       extent=[xs[0], xs[-1], ys[0], ys[-1]], interpolation='bilinear')
        ax.contour(np.linspace(ext[0], ext[1], support.shape[1])[::4],
                   np.linspace(ext[2], ext[3], support.shape[0])[::4],
                   support[::4, ::4].astype(float), levels=[0.5], colors='#1f3a5a',
                   linewidths=0.3, alpha=0.35)
        X, Y = np.meshgrid(xs, ys)
        bad = np.nan_to_num(gap, nan=0) >= 180
        ax.scatter(X[bad], Y[bad], s=2, c='black', marker='.', linewidths=0)
        ax.set_xlim(ext[0], ext[1])
        ax.set_ylim(ext[2], ext[3])
        ax.set_title(f'{label}：颜色 = 杯脚压在筋顶上的比例；黑点 = 支撑全挤在半圈内（会往一侧歪）'
                     f'\n可放位置 {summ["samples"]} 个，单侧受力 {summ["one_sided_count"]} 个'
                     f'（{summ["one_sided_pct"]}%），接触中位 {summ["contact_median_pct"]}%',
                     fontsize=10, loc='left')
        fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01, label='接触 %')
    for ax in axes:
        ax.set_aspect('equal')
        ax.tick_params(labelsize=8)
    fig.suptitle(title, fontsize=13, x=0.01, ha='left')
    fig.savefig(path, dpi=150)
    plt.close(fig)


def parse_foot(s):
    d, _, kind = s.partition(':')
    if kind not in ('', 'ring', 'flat'):
        raise argparse.ArgumentTypeError('杯脚格式：30 或 30:ring 或 45:flat')
    return float(d), kind == 'flat'


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('stl', type=Path)
    p.add_argument('--out-dir', type=Path, required=True)
    p.add_argument('--foot', type=parse_foot, action='append',
                   help='杯脚直径 mm，可加 :flat 表示平底；可重复。默认 30（圈足）')
    p.add_argument('--crown-z', type=float, help='承杯面（筋顶）高度；默认自动识别')
    p.add_argument('--step', type=float, default=2.0, help='杯心网格间距 mm')
    p.add_argument('--at', action='append', default=[], help='检查指定杯心 x,y（STL 坐标，mm）')
    p.add_argument('--title', default='杯子放上去稳不稳')
    a = p.parse_args()
    feet = a.foot or [(30.0, False)]

    mesh = trimesh.load(a.stl, force='mesh')
    if a.crown_z is None:
        crown, planes = detect_crown(mesh)
    else:
        crown, planes = a.crown_z, horizontal_planes(mesh)
    tris = mesh.triangles
    up = mesh.face_normals[:, 2] > 0.999
    on_crown = up & (np.abs(tris[:, :, 2].mean(1) - crown) < 0.02)
    higher = tris[:, :, 2].max(1) > crown + 0.05
    rs = Raster(mesh.bounds)
    support = rs.draw(tris[on_crown])
    blocked = rs.draw(tris[higher])
    inside = rs.draw(tris)

    (x0, y0), (x1, y1) = mesh.bounds[0][:2], mesh.bounds[1][:2]
    xs = np.arange(x0, x1 + 1e-9, a.step)
    ys = np.arange(y0, y1 + 1e-9, a.step)
    X, Y = np.meshgrid(xs, ys)
    centres = np.column_stack([X.ravel(), Y.ravel()])
    probes = np.array([[float(v) for v in s.split(',')] for s in a.at]) if a.at else np.zeros((0, 2))

    a.out_dir.mkdir(parents=True, exist_ok=True)
    report = dict(stl=str(a.stl), crown_z=crown, support_share_pct=round(100 * float(
        support.sum() / max(1, inside.sum())), 1),
        horizontal_planes_mm2={f'{k:.2f}': round(v) for k, v in planes.items()},
        method='几何判据：支撑全落在半圈内即判为单侧受力；不含摩擦、杯重分布、打印误差和实物验证',
        feet=[], probes=[])
    results = []
    for d, flat in feet:
        res, valid = analyse(rs, support, blocked, inside, centres, d, flat)
        if not valid.any():
            raise SystemExit(f'{d}mm 杯脚在盘内找不到可放位置')
        summ = summarise(res, valid, d, flat)
        report['feet'].append(summ)
        results.append((summ['foot'], res, summ))
        if len(probes):
            pr, pv = analyse(rs, support, blocked, inside, probes, d, flat)
            for (px, py), c, g, v in zip(probes, pr['contact'], pr['gap'], pv):
                report['probes'].append(dict(foot=summ['foot'], at=[px, py], fits=bool(v),
                                             contact_pct=None if not v else round(float(c), 1),
                                             max_gap_deg=None if not v else round(float(g), 1),
                                             one_sided=None if not v else bool(g >= 180)))
        print(json.dumps(summ, ensure_ascii=False), flush=True)

    png = a.out_dir / 'cup_stability.png'
    render(png, rs, support, xs, ys, results, crown, a.title, report['support_share_pct'])
    report['figure'] = str(png)
    (a.out_dir / 'cup_stability.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for pr in report['probes']:
        print('probe', json.dumps(pr, ensure_ascii=False))
    print(f'→ {png}')


if __name__ == '__main__':
    main()

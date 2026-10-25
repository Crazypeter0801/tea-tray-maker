"""Parametric ripple tea tray, derived from the user's v4i CAD source.
Units: mm. Generates STEP/STL plus geometry-only validation, never a print job.
Run with cadquery==2.5.2. Default dimensions reproduce the historical v4i geometry.
"""
import argparse
import json
from pathlib import Path
from collections import Counter
import cadquery as cq
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box

LENGTH, WIDTH, HEIGHT = 240.0, 148.3, 12.0
CORNER_RADIUS = 30.0
FLOOR, GROOVE_DEPTH = 3.0, 6.0
PITCH = 5.5
RIDGE_TOP_WIDTH, RIDGE_BASE_WIDTH = 2.2, 2.2   # 等宽直壁；沟净宽 = 5.5 - 2.2 = 3.3
FIRST_RING_RADIUS = 3.6
EDGE_CLEARANCE = 0.4
RIM_WIDTH, MOAT_WIDTH = 3.8, 2.4
# 圆环与横纹之间的分隔沟 = 与筋间沟同宽。
# 推导：外圈筋外缘 = (RADIUS - SEP) - 0.2；横纹起点 = RADIUS + SEP
#       => 分隔沟 = 2*SEP + 0.2  =>  SEP = (GROOVE - 0.2) / 2
GROOVE_WIDTH = PITCH - RIDGE_BASE_WIDTH                  # 3.3，筋间沟
PATTERN_SEPARATOR_HALF_WIDTH = (GROOVE_WIDTH - 0.2) / 2  # 1.55 -> 分隔沟 3.3
STL_LINEAR_TOLERANCE = 0.01
STL_ANGULAR_TOLERANCE = 0.03

# Ring families. Each family's centre sits on a corner-fillet centre, so the rings
# stay concentric with the R30 corner arcs instead of being sliced by them.
# 半径 = 遮罩半径 + SEP。遮罩半径（115.55-0.65 / 78.55-0.65）保持不变，
# 所以每道筋的中心线位置与 v4h 完全一致；SEP 加大只把横纹的起点往外推。
LEFT_RADIUS, RIGHT_RADIUS = 116.45, 79.45
# 左上角倒角圆心 = (CORNER_RADIUS, WIDTH - CORNER_RADIUS)
LEFT_CY = WIDTH - CORNER_RADIUS          # = 118.3
# 右扇：沿 45 deg 把圆心推到 (237, 3)——正是 v14 的 ARC_C，几乎压在盘外角上，
# 于是内侧几圈天然落在材料外，露出来的是一把大扫弧。
RIGHT_SHIFT = 38.1838                    # = 27 * sqrt(2) -> c2 = (237, 3)
# 左环从 3.6 起（带圆心孔）；右扇从 21.6 起，与 v14 的 ARC_R0 一致
FIRST_RING_RADIUS, RIGHT_FIRST_RADIUS = 3.6, 21.6


def rounded_prism(inset, z, height):
    w, h = LENGTH - 2 * inset, WIDTH - 2 * inset
    r = CORNER_RADIUS - inset
    return (cq.Workplane('XY').center(LENGTH / 2, WIDTH / 2)
            .box(w, h, height, centered=(True, True, False)).edges('|Z').fillet(r)
            .val().translate((0, 0, z)))


def cylinder(center, radius, z=None, height=None):
    z = FLOOR if z is None else z
    height = GROOVE_DEPTH if height is None else height
    return cq.Solid.makeCylinder(radius, height, cq.Vector(*center, z))


def circular_ridge(center, r):
    """等宽时用圆柱（makeCone 不接受 R1 == R2）。"""
    z0 = cq.Vector(*center, FLOOR)
    if RIDGE_BASE_WIDTH == RIDGE_TOP_WIDTH:
        outer = cq.Solid.makeCylinder(r + RIDGE_TOP_WIDTH / 2, GROOVE_DEPTH, z0)
        inner = cq.Solid.makeCylinder(r - RIDGE_TOP_WIDTH / 2, GROOVE_DEPTH, z0)
    else:
        outer = cq.Solid.makeCone(r + RIDGE_BASE_WIDTH / 2, r + RIDGE_TOP_WIDTH / 2,
                                  GROOVE_DEPTH, z0)
        inner = cq.Solid.makeCone(r - RIDGE_BASE_WIDTH / 2, r - RIDGE_TOP_WIDTH / 2,
                                  GROOVE_DEPTH, z0)
    return outer.cut(inner)


def straight_ridge(y):
    return (cq.Workplane('YZ').polyline([
        (y - RIDGE_BASE_WIDTH / 2, FLOOR), (y + RIDGE_BASE_WIDTH / 2, FLOOR),
        (y + RIDGE_TOP_WIDTH / 2, FLOOR + GROOVE_DEPTH),
        (y - RIDGE_TOP_WIDTH / 2, FLOOR + GROOVE_DEPTH)])
        .close().extrude(LENGTH).val())


def build():
    assert 0 < FLOOR < FLOOR + GROOVE_DEPTH < HEIGHT
    assert 0 < RIDGE_TOP_WIDTH <= RIDGE_BASE_WIDTH < PITCH
    assert RIM_WIDTH + MOAT_WIDTH < CORNER_RADIUS
    base = rounded_prism(0, 0, HEIGHT).cut(rounded_prism(RIM_WIDTH, FLOOR, HEIGHT))
    base = cq.Workplane(obj=base).faces('>Z').edges().chamfer(0.5).val()
    domain = rounded_prism(RIM_WIDTH + MOAT_WIDTH, FLOOR, GROOVE_DEPTH)
    c1 = (CORNER_RADIUS, LEFT_CY)
    c2 = (LENGTH - CORNER_RADIUS + RIGHT_SHIFT / 2 ** 0.5,
          CORNER_RADIUS - RIGHT_SHIFT / 2 ** 0.5)
    r1, r2 = LEFT_RADIUS, RIGHT_RADIUS
    gap = PATTERN_SEPARATOR_HALF_WIDTH
    mask1 = domain.intersect(cylinder(c1, r1 - gap))
    mask2 = domain.intersect(cylinder(c2, r2 - gap)).cut(cylinder(c1, r1 + gap))
    mask_straight = domain.cut(cylinder(c1, r1 + gap)).cut(cylinder(c2, r2 + gap))
    ribs = []
    audit = []

    def retain_full_height(shape):
        for solid in shape.Solids():
            crown_area = sum(f.Area() for f in solid.Faces()
                             if f.geomType() == 'PLANE'
                             and abs(f.Center().z - (FLOOR + GROOVE_DEPTH)) < 1e-5
                             and abs(f.normalAt().z) > 0.999)
            if crown_area >= RIDGE_TOP_WIDTH ** 2 and solid.Volume() > 1e-6:
                ribs.append(solid)

    for name, center, radius, mask, first in [('left', c1, r1, mask1, FIRST_RING_RADIUS),
                                              ('right', c2, r2, mask2, RIGHT_FIRST_RADIUS)]:
        last_radius = radius - gap - RIDGE_BASE_WIDTH / 2 - 0.2
        intervals = max(1, round((last_radius - first) / PITCH))
        pitch = (last_radius - first) / intervals
        radii = [first + k * pitch for k in range(intervals + 1)]
        assert radii[-1] + RIDGE_BASE_WIDTH / 2 < radius - gap
        for radius_i in radii:
            retain_full_height(circular_ridge(center, radius_i).intersect(mask))
        audit.append({'region': name, 'center_mm': center, 'radii_mm': radii,
                      'actual_pitch_mm': pitch, 'outer_ring_radial_clearance_mm': 0.2})
        print(f'{name}: {len(radii)} full-width rings, pitch {pitch:.4f} mm', flush=True)

    start = RIM_WIDTH + MOAT_WIDTH + RIDGE_BASE_WIDTH / 2 + EDGE_CLEARANCE
    end = WIDTH - start
    intervals = max(1, round((end - start) / PITCH))
    pitch = (end - start) / intervals
    for k in range(intervals + 1):
        retain_full_height(straight_ridge(start + k * pitch).intersect(mask_straight))
    audit.append({'region': 'straight', 'first_center_y_mm': start, 'last_center_y_mm': end,
                  'count': intervals + 1, 'actual_pitch_mm': pitch,
                  'edge_clearance_mm': EDGE_CLEARANCE})
    build.layout_audit = audit
    print(f'Fusing {len(ribs)} ribs to the base', flush=True)
    result = base.fuse(*ribs).clean()
    assert result.isValid() and len(result.Solids()) == 1
    return result


def configure(a):
    """Keep the pattern's layout proportions, but do not scale printable rib widths."""
    import math
    global LENGTH, WIDTH, HEIGHT, FLOOR, GROOVE_DEPTH, CORNER_RADIUS
    global RIDGE_TOP_WIDTH, RIDGE_BASE_WIDTH, PITCH, GROOVE_WIDTH
    global PATTERN_SEPARATOR_HALF_WIDTH, LEFT_RADIUS, RIGHT_RADIUS, LEFT_CY, RIGHT_SHIFT
    values = (a.length, a.width, a.height, a.floor, a.rib_height, a.rib_width, a.pitch)
    if not all(math.isfinite(v) and v > 0 for v in values):
        raise ValueError('All dimensions must be finite and positive')
    if not (a.floor < a.floor + a.rib_height < a.height):
        raise ValueError('Require floor + rib-height < height (rim above ribs)')
    if a.pitch - a.rib_width <= 0.2:
        raise ValueError('pitch must exceed rib-width by more than 0.2 mm')
    if a.rib_width >= 2 * FIRST_RING_RADIUS:
        raise ValueError('rib-width would close the innermost ring')
    scale = min(a.length / 240, a.width / 148.3)
    if not 0.65 <= scale <= 1.5 or not 1.2 <= a.length / a.width <= 2.2:
        raise ValueError('Outside seed layout range; edit the CAD layout instead of forcing these dimensions')
    LENGTH, WIDTH, HEIGHT = a.length, a.width, a.height
    FLOOR, GROOVE_DEPTH = a.floor, a.rib_height
    RIDGE_TOP_WIDTH = RIDGE_BASE_WIDTH = a.rib_width
    PITCH = a.pitch
    CORNER_RADIUS = 30 * scale
    LEFT_CY = WIDTH - CORNER_RADIUS
    RIGHT_SHIFT = (CORNER_RADIUS - 3 * scale) * 2 ** 0.5
    GROOVE_WIDTH = PITCH - RIDGE_BASE_WIDTH
    PATTERN_SEPARATOR_HALF_WIDTH = (GROOVE_WIDTH - 0.2) / 2
    # Maintain mask radii independently from separator width.
    LEFT_RADIUS = 114.9 * scale + PATTERN_SEPARATOR_HALF_WIDTH
    RIGHT_RADIUS = 77.9 * scale + PATTERN_SEPARATOR_HALF_WIDTH


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, default=Path('.'))
    p.add_argument('--length', type=float, default=240)
    p.add_argument('--width', type=float, default=148.3)
    p.add_argument('--height', type=float, default=12)
    p.add_argument('--floor', type=float, default=3)
    p.add_argument('--rib-height', type=float, default=6)
    p.add_argument('--rib-width', type=float, default=2.2)
    p.add_argument('--pitch', type=float, default=5.5)
    a = p.parse_args()
    configure(a)
    out = a.out
    existing = [out / name for name in ('tea_tray.step', 'tea_tray.stl', 'validation.json')
                if (out / name).exists()]
    if existing:
        raise FileExistsError('Choose a new output directory; existing artifacts: ' + str(existing))
    out.mkdir(parents=True, exist_ok=True)
    shape = build()
    stem = 'tea_tray'
    cq.exporters.export(shape, str(out / (stem + '.step')))
    shape.exportStl(str(out / (stem + '.stl')), tolerance=STL_LINEAR_TOLERANCE,
                    angularTolerance=STL_ANGULAR_TOLERANCE, relative=False, parallel=True)
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, b, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = b.Get()
    ratio = (xmax - xmin) / (ymax - ymin)
    stats = {'cad_valid': shape.isValid(), 'solid_count': len(shape.Solids()),
             'dimensions_mm': [xmax - xmin, ymax - ymin, zmax - zmin],
             'corner_radius_mm': CORNER_RADIUS,
             'aspect_ratio': ratio, 'golden_ratio_deviation_pct': (ratio / 1.618034 - 1) * 100,
             'material_volume_ml': shape.Volume() / 1000,
             'face_types': dict(Counter(f.geomType() for f in shape.Faces())),
             'edge_types': dict(Counter(e.geomType() for e in shape.Edges())),
             'stl_absolute_linear_tolerance_mm': STL_LINEAR_TOLERANCE,
             'stl_angular_tolerance_radians': STL_ANGULAR_TOLERANCE,
             'cup_sizes_confirmed': False, 'printer_confirmed': False,
             'slicer_verified': False, 'physical_print_verified': False,
             'capacity_note': 'Geometric void volume below absolute Z; not measured watertight capacity',
             'parameters': {k: v for k, v in vars(a).items() if k != 'out'},
             'layout_audit': build.layout_audit,
             'ridge_top_width_mm': RIDGE_TOP_WIDTH,
             'ridge_base_width_mm': RIDGE_BASE_WIDTH,
             'center_hole_floor_diameter_mm': 2 * FIRST_RING_RADIUS - RIDGE_BASE_WIDTH,
             'center_hole_top_diameter_mm': 2 * FIRST_RING_RADIUS - RIDGE_TOP_WIDTH}
    stats['geometric_capacity_ml'] = {}
    for level in sorted(set((FLOOR + GROOVE_DEPTH - 1, FLOOR + GROOVE_DEPTH, HEIGHT - 1))):
        if level <= FLOOR:
            continue
        water = rounded_prism(RIM_WIDTH, FLOOR, level - FLOOR).cut(shape)
        stats['geometric_capacity_ml'][str(level)] = water.Volume() / 1000
    (out / 'validation.json').write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2), flush=True)


if __name__ == '__main__':
    main()

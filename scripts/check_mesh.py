#!/usr/bin/env python3
"""Check exported STL topology and compare against the CAD build report."""
import argparse
import json
from pathlib import Path
import numpy as np
import trimesh


def count_components(mesh):
    """Face-connected parts via union-find; avoids trimesh's optional graph engines
    (mesh.split needs networkx/scipy and raises 'no graph engines available' without them)."""
    parent = np.arange(len(mesh.faces))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in mesh.face_adjacency:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return len({find(i) for i in range(len(parent))})


def check(path, cad_report=None):
    mesh = trimesh.load(path, force='mesh', process=True)
    if not len(mesh.faces):
        raise ValueError('Empty mesh')
    _, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    report = dict(watertight=bool(mesh.is_watertight),
                  winding_consistent=bool(mesh.is_winding_consistent),
                  is_volume=bool(mesh.is_volume), boundary_edges=int((counts == 1).sum()),
                  nonmanifold_edges=int((counts > 2).sum()),
                  connected_components=count_components(mesh),
                  dimensions_mm=mesh.extents.tolist(), volume_ml=float(mesh.volume / 1000),
                  faces=len(mesh.faces), physical_print_verified=False)
    failures = []
    if not report['is_volume'] or not report['watertight'] or not report['winding_consistent']:
        failures.append('Mesh must be a closed, consistently wound positive-volume solid')
    if report['boundary_edges'] or report['nonmanifold_edges'] or report['connected_components'] != 1:
        failures.append('Open, non-manifold or disconnected geometry')
    if cad_report:
        cad = json.loads(Path(cad_report).read_text())
        if not np.allclose(mesh.extents, cad['dimensions_mm'], atol=.05, rtol=0):
            failures.append('STL/CAD dimensions differ by more than 0.05 mm')
        relative_error = abs(report['volume_ml'] - cad['material_volume_ml']) / cad['material_volume_ml']
        report['cad_volume_relative_error'] = relative_error
        if relative_error > .005:
            failures.append('STL/CAD volume differs by more than 0.5 percent')
    report['failures'] = failures
    report['geometry_passed'] = not failures
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stl', type=Path)
    p.add_argument('--cad-report', type=Path)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    result = check(a.stl, a.cad_report)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return int(not result['geometry_passed'])


if __name__ == '__main__':
    raise SystemExit(main())

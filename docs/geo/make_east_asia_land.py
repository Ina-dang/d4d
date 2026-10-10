"""world-atlas(countries-50m, Natural Earth 기반, ISC)에서 동아시아 육지만 잘라 east-asia-land.json을 만든다.

스토리보드는 CSP(script-src·connect-src 'self') 때문에 CDN의 D3·지도 데이터를 쓸 수 없어,
잘라낸 육지 윤곽을 저장소에 두고 직접 그린다.

사용: python docs/geo/make_east_asia_land.py countries-50m.json
      (https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json)
출력: docs/geo/east-asia-land.json  {"bbox": [...], "rings": [[[lon, lat], ...], ...]}
"""
import json
import sys
from pathlib import Path

BBOX = (55.0, -12.0, 180.0, 62.0)  # 경도·위도 범위. 넓고 낮은 패널에서도 빈 곳이 없도록 넉넉히
MIN_STEP = 0.1                    # 이보다 가까운 연속 점은 버린다(도)


def decode_arcs(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    out = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            pts.append((x * sx + tx, y * sy + ty))
        out.append(pts)
    return out


def ring_coords(ring, arcs):
    pts = []
    for i in ring:
        a = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts.extend(a if not pts else a[1:])
    return pts


def clip(ring, box):
    """Sutherland–Hodgman: 고리를 사각형으로 자른다."""
    x0, y0, x1, y1 = box
    edges = [(lambda p: p[0] >= x0, lambda a, b: (x0, a[1] + (b[1] - a[1]) * (x0 - a[0]) / (b[0] - a[0]))),
             (lambda p: p[0] <= x1, lambda a, b: (x1, a[1] + (b[1] - a[1]) * (x1 - a[0]) / (b[0] - a[0]))),
             (lambda p: p[1] >= y0, lambda a, b: (a[0] + (b[0] - a[0]) * (y0 - a[1]) / (b[1] - a[1]), y0)),
             (lambda p: p[1] <= y1, lambda a, b: (a[0] + (b[0] - a[0]) * (y1 - a[1]) / (b[1] - a[1]), y1))]
    out = ring
    for inside, cross in edges:
        if not out:
            break
        src, out = out, []
        for i, cur in enumerate(src):
            prev = src[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
    return out


def simplify(ring):
    out = []
    for x, y in ring:
        if not out or abs(x - out[-1][0]) + abs(y - out[-1][1]) >= MIN_STEP:
            out.append([round(x, 2), round(y, 2)])
    return out if len(out) >= 4 else []


def main(src):
    topo = json.loads(Path(src).read_text(encoding="utf-8"))
    arcs = decode_arcs(topo)
    rings = []
    for geom in topo["objects"]["land"]["geometries"]:
        polys = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
        for poly in polys:
            for ring in poly:
                r = simplify(clip(ring_coords(ring, arcs), BBOX))
                if r:
                    rings.append(r)
    out = Path(__file__).with_name("east-asia-land.json")
    out.write_text(json.dumps({"source": "world-atlas@2.0.2 countries-50m (Natural Earth), ISC",
                               "bbox": BBOX, "rings": rings}, separators=(",", ":")), encoding="utf-8")
    print(f"{out}: 고리 {len(rings)}개, {out.stat().st_size // 1024}KB")


if __name__ == "__main__":
    main(sys.argv[1])

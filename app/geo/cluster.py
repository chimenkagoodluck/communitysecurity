from __future__ import annotations

import math
from typing import Optional, Sequence

EARTH_RADIUS_M = 6_371_000.0

_UNVISITED = -2
_NOISE = -1


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def dbscan(
    points: Sequence[tuple[float, float]],
    eps_m: float,
    min_samples: int,
    weights: Optional[Sequence[float]] = None,
) -> list[int]:
    
    n = len(points)
    w = [1.0] * n if weights is None else list(weights)
    labels = [_UNVISITED] * n

    def neighbours(i: int) -> list[int]:
        lat_i, lon_i = points[i]
        return [j for j in range(n)
                if haversine_m(lat_i, lon_i, points[j][0], points[j][1]) <= eps_m]

    def is_core(nb: list[int]) -> bool:
        return sum(w[j] for j in nb) >= min_samples

    cluster_id = -1
    for i in range(n):
        if labels[i] != _UNVISITED:
            continue
        nb = neighbours(i)
        if not is_core(nb):
            labels[i] = _NOISE          # too sparse to seed a cluster (for now)
            continue
        cluster_id += 1
        labels[i] = cluster_id
        seeds = [j for j in nb if j != i]
        k = 0
        while k < len(seeds):
            j = seeds[k]
            if labels[j] == _NOISE:
                labels[j] = cluster_id   # a former noise point is a border point
            elif labels[j] == _UNVISITED:
                labels[j] = cluster_id
                jnb = neighbours(j)
                if is_core(jnb):              # j is itself a core point -> expand
                    for x in jnb:
                        if x not in seeds:
                            seeds.append(x)
            k += 1
    return labels

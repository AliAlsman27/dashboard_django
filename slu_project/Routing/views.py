"""
Routing views — Route Management Dashboard

BOTH routes only collect bins with level >= FILL_THRESHOLD (70%).

Route types differ in HOW they optimise:

  faster   — OSRM /trip endpoint: OSRM solves the TSP internally on the
              real road network, optimising for *minimum travel time*.
              The road network drives the ordering (traffic, road speeds).

  low_co2  — We run 2-opt to find the *minimum-distance* waypoint order,
              then submit that FIXED order to OSRM /route.
              Minimising km driven → less fuel → lower CO₂.

Because one uses time-optimal trip ordering and the other uses
distance-optimal fixed ordering, the resulting paths differ visibly.
OSRM public API: http://router.project-osrm.org  (no API key)
"""

import math
import json
import urllib.request
from django.shortcuts import render
from django.http import JsonResponse
from .firebase_client import get_all_stations, get_stations_by_zone, get_zone_names

OSRM_BASE       = "http://router.project-osrm.org"
FILL_THRESHOLD  = 70   # collect bins at or above this fill level (%)


# ────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ────────────────────────────────────────────────────────────────────────────

def _haversine(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance in metres."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _total_distance(route: list) -> float:
    return sum(
        _haversine(route[i]["lat"], route[i]["lng"],
                   route[i+1]["lat"], route[i+1]["lng"])
        for i in range(len(route) - 1)
    )


# ────────────────────────────────────────────────────────────────────────────
# TSP optimisation
# ────────────────────────────────────────────────────────────────────────────

def _greedy_nn(points: list) -> list:
    """Greedy nearest-neighbour TSP. Start from centroid-nearest point."""
    if not points:
        return []
    remaining = points[:]
    clat = sum(p["lat"] for p in remaining) / len(remaining)
    clng = sum(p["lng"] for p in remaining) / len(remaining)
    si = min(range(len(remaining)),
             key=lambda i: _haversine(clat, clng, remaining[i]["lat"], remaining[i]["lng"]))
    route = [remaining.pop(si)]
    while remaining:
        last = route[-1]
        ni = min(range(len(remaining)),
                 key=lambda i: _haversine(last["lat"], last["lng"],
                                          remaining[i]["lat"], remaining[i]["lng"]))
        route.append(remaining.pop(ni))
    return route


def _two_opt(route: list) -> list:
    """
    2-opt local-search: minimise total haversine distance.
    Iteratively reverses sub-segments whose swap reduces total path length.
    This is the distance-minimising step for the Low-CO₂ route.
    """
    if len(route) < 4:
        return route[:]
    best = route[:]
    improved = True
    while improved:
        improved = False
        n = len(best)
        for i in range(n - 1):
            for j in range(i + 2, n):
                # Skip wrap-around for open path
                if j == n - 1 and i == 0:
                    continue
                a, b = best[i],  best[i + 1]
                c, d = best[j],  best[(j + 1) % n]
                # Cost of current edges
                curr = _haversine(a["lat"], a["lng"], b["lat"], b["lng"]) + \
                       _haversine(c["lat"], c["lng"], d["lat"], d["lng"])
                # Cost after 2-opt swap
                swap = _haversine(a["lat"], a["lng"], c["lat"], c["lng"]) + \
                       _haversine(b["lat"], b["lng"], d["lat"], d["lng"])
                if swap < curr - 0.5:   # 0.5 m tolerance
                    best[i+1:j+1] = list(reversed(best[i+1:j+1]))
                    improved = True
    return best


# ────────────────────────────────────────────────────────────────────────────
# OSRM calls — two distinct functions for the two route strategies
# ────────────────────────────────────────────────────────────────────────────

def _osrm_trip(points: list) -> dict:
    """
    FASTER ROUTE — OSRM /trip endpoint.
    OSRM solves the TSP internally for minimum travel TIME on actual roads.
    Waypoints may be reordered by OSRM. The reordered stops are returned.
    """
    if len(points) < 2:
        return {"geometry": [], "distance_km": 0, "duration_min": 0,
                "ordered_waypoints": points, "source": "none"}

    coords_str = ";".join(f"{p['lng']},{p['lat']}" for p in points)
    url = (
        f"{OSRM_BASE}/trip/v1/driving/{coords_str}"
        f"?roundtrip=false&source=first&destination=last"
        f"&overview=full&geometries=geojson&steps=false"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())

        if data.get("code") == "Ok" and data.get("trips"):
            trip = data["trips"][0]
            latlngs = [[c[1], c[0]] for c in trip["geometry"]["coordinates"]]

            # Recover OSRM's optimised stop order from the waypoints array
            osrm_waypoints = data.get("waypoints", [])
            ordered = list(points)  # default
            if osrm_waypoints:
                trip_idx = [w.get("trips_index", 0) for w in osrm_waypoints]
                # waypoint_index gives position within the trip
                wp_order = [w.get("waypoint_index", i) for i, w in enumerate(osrm_waypoints)]
                paired = sorted(zip(wp_order, points), key=lambda x: x[0])
                ordered = [p for _, p in paired]

            return {
                "geometry":         latlngs,
                "distance_km":      round(trip["distance"] / 1000, 2),
                "duration_min":     round(trip["duration"] / 60, 1),
                "ordered_waypoints": ordered,
                "source":           "osrm",
            }
    except Exception as exc:
        print(f"[OSRM /trip] error: {exc}")

    # ── Fallback: greedy NN + straight lines ───────────────────────────────
    ordered = _greedy_nn(points)
    latlngs = [[p["lat"], p["lng"]] for p in ordered]
    dist_m  = _total_distance(ordered)
    return {
        "geometry":          latlngs,
        "distance_km":       round(dist_m / 1000, 2),
        "duration_min":      round(dist_m / 1000 / 30 * 60, 1),
        "ordered_waypoints": ordered,
        "source":            "fallback",
    }


def _osrm_route_fixed(ordered_points: list) -> dict:
    """
    LOW CO₂ ROUTE — OSRM /route endpoint with FIXED waypoint order.
    Waypoint order has been pre-optimised by 2-opt to minimise total distance.
    OSRM draws the actual road path between them in that exact order.
    """
    if len(ordered_points) < 2:
        return {"geometry": [], "distance_km": 0, "duration_min": 0, "source": "none"}

    coords_str = ";".join(f"{p['lng']},{p['lat']}" for p in ordered_points)
    url = (
        f"{OSRM_BASE}/route/v1/driving/{coords_str}"
        f"?overview=full&geometries=geojson&steps=false"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())

        if data.get("code") == "Ok" and data.get("routes"):
            r = data["routes"][0]
            latlngs = [[c[1], c[0]] for c in r["geometry"]["coordinates"]]
            return {
                "geometry":     latlngs,
                "distance_km":  round(r["distance"] / 1000, 2),
                "duration_min": round(r["duration"] / 60, 1),
                "source":       "osrm",
            }
    except Exception as exc:
        print(f"[OSRM /route] error: {exc}")

    # Fallback
    latlngs = [[p["lat"], p["lng"]] for p in ordered_points]
    dist_m  = _total_distance(ordered_points)
    return {
        "geometry":     latlngs,
        "distance_km":  round(dist_m / 1000, 2),
        "duration_min": round(dist_m / 1000 / 30 * 60, 1),
        "source":       "fallback",
    }


# ────────────────────────────────────────────────────────────────────────────
# Priority bin filter
# ────────────────────────────────────────────────────────────────────────────

def _priority_bins(zone_stations: dict) -> list:
    """Filter to active bins at or above FILL_THRESHOLD."""
    result = []
    for sid, s in zone_stations.items():
        if not (s.get("lat") and s.get("lng")):
            continue
        if s.get("level", 0) >= FILL_THRESHOLD and s.get("status") != "Under Maintenance":
            result.append({
                "id":    sid,
                "lat":   float(s["lat"]),
                "lng":   float(s["lng"]),
                "level": s.get("level", 0),
                "type":  s.get("type", ""),
                "status": s.get("status", "Active"),
            })
    return result


# ────────────────────────────────────────────────────────────────────────────
# Django views
# ────────────────────────────────────────────────────────────────────────────

def route_management(request):
    stations   = get_all_stations()
    vals       = [v for v in stations.values() if isinstance(v, dict)]

    full_bins  = sum(1 for s in vals if s.get("level", 0) >= 80)
    semi_full  = sum(1 for s in vals if 40 <= s.get("level", 0) < 80)
    empty_bins = sum(1 for s in vals if s.get("level", 0) < 40)
    maintenance = sum(1 for s in vals if s.get("status") == "Under Maintenance")

    stations_json = json.dumps([
        {"id": k, "lat": float(v["lat"]), "lng": float(v["lng"]),
         "level": v.get("level", 0), "zone": v.get("zone", ""),
         "type": v.get("type", ""), "status": v.get("status", "Active")}
        for k, v in stations.items()
        if isinstance(v, dict) and v.get("lat") and v.get("lng")
    ])

    context = {
        "full_bins":         full_bins,
        "semi_full_bins":    semi_full,
        "empty_bins":        empty_bins,
        "under_maintenance": maintenance,
        "zones":             get_zone_names(),
        "stations_json":     stations_json,
        "fill_threshold":    FILL_THRESHOLD,
    }
    return render(request, "Routing/route_management.html", context)


def api_stations(request):
    stations = get_all_stations()
    data = [
        {"id": k, "lat": float(v["lat"]), "lng": float(v["lng"]),
         "level": v.get("level", 0), "zone": v.get("zone", ""),
         "type": v.get("type", ""), "status": v.get("status", "Active")}
        for k, v in stations.items()
        if isinstance(v, dict) and v.get("lat") and v.get("lng")
    ]
    return JsonResponse({"stations": data})


def api_optimized_route(request):
    """
    GET /routing/api/optimized-route/?zone=<name>&type=<faster|low_co2>

    Both modes filter to bins >= 70%.

    faster:
        Uses OSRM /trip — OSRM reorders stops for minimum TRAVEL TIME
        on the real road network (considers traffic & road speeds).

    low_co2:
        We reorder stops with 2-opt to minimise TOTAL DISTANCE (km).
        Then call OSRM /route with that fixed order.
        Less km driven = less fuel burned = less CO₂ emitted.

    The two routes will differ visually because:
      - faster:  OSRM picks the time-optimal road path & stop order
      - low_co2: We pick the distance-minimal order, OSRM draws roads for it
    """
    zone       = request.GET.get("zone", "").strip()
    route_type = request.GET.get("type", "faster")

    if not zone:
        return JsonResponse({"error": "zone parameter is required"}, status=400)

    zone_stations = get_stations_by_zone(zone)
    if not zone_stations:
        return JsonResponse({"waypoints": [], "geometry": [],
                             "message": f'No stations in zone "{zone}".'})

    total_in_zone = len(zone_stations)
    priority = _priority_bins(zone_stations)
    bins_skipped = total_in_zone - len(priority)

    if not priority:
        return JsonResponse({
            "waypoints":    [],
            "geometry":     [],
            "bins_skipped": bins_skipped,
            "message":      f"All {total_in_zone} bins in '{zone}' are below "
                            f"{FILL_THRESHOLD}% — no collection needed.",
        })

    if route_type == "low_co2":
        # ── Distance-minimised 2-opt → OSRM /route (fixed order) ──────────
        greedy  = _greedy_nn(priority)
        ordered = _two_opt(greedy)
        road    = _osrm_route_fixed(ordered)
        label   = "Lower CO\u2082 (distance-minimised, 2-opt TSP)"

        return JsonResponse({
            "waypoints":    ordered,
            "geometry":     road["geometry"],
            "distance_km":  road["distance_km"],
            "duration_min": road["duration_min"],
            "source":       road["source"],
            "route_type":   "low_co2",
            "route_label":  label,
            "bins_skipped": bins_skipped,
            "threshold":    FILL_THRESHOLD,
        })
    else:
        # ── OSRM /trip — time-optimal TSP solved on real road network ──────
        road    = _osrm_trip(priority)
        ordered = road.pop("ordered_waypoints", priority)
        label   = "Faster (time-optimal, OSRM trip solver)"

        return JsonResponse({
            "waypoints":    ordered,
            "geometry":     road["geometry"],
            "distance_km":  road["distance_km"],
            "duration_min": road["duration_min"],
            "source":       road["source"],
            "route_type":   "faster",
            "route_label":  label,
            "bins_skipped": bins_skipped,
            "threshold":    FILL_THRESHOLD,
        })

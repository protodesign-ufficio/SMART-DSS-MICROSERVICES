"""
Multi-objective Pareto-optimal scheduling solver using NAMOA* algorithm.
"""
from __future__ import annotations
import heapq
import math
from typing import Any, Dict, List, Optional, Tuple

from models import Route, Vessel


def prob_overload_normal(mu: float, sigma: float, cap: float) -> float:
    """Calculate probability of overload assuming normal distribution."""
    if sigma <= 0:
        return 1.0 if mu > cap else 0.0
    z = (cap - mu) / (sigma * math.sqrt(2))
    return 0.5 * (1 - math.erf(z))


def build_reposition_lookup(
    routes: List[Route],
    reposition_view: Optional[Dict[Tuple[str, str, str], Dict[str, Any]]] = None,
) -> Dict[Tuple[str, str, str], Tuple[int, float]]:
    """
    Build reposition lookup by (origin, destination, vessel_id).
    If reposition_view is supplied, use it; otherwise infer from routes.
    """
    lookup: Dict[Tuple[str, str, str], Tuple[int, float]] = {}

    if reposition_view is not None:
        for (o, d, v), data in reposition_view.items():
            dur_s = int(float(data["tempo_riposizionamento"]) * 60)
            cost = float(data["consumo_riposizionamento"])
            lookup[(o, d, v)] = (dur_s, cost)
        return lookup

    for r in routes:
        key = (r.origin, r.destination, r.vessel_id)
        if key not in lookup:
            lookup[key] = (r.duration_s, r.consumo)
        else:
            best_dur, best_cost = lookup[key]
            lookup[key] = (min(best_dur, r.duration_s), min(best_cost, r.consumo))

    return lookup


def build_problem(
    routes: List[Route],
    vessels: Dict[str, Vessel],
    reposition_view: Optional[Dict[Tuple[str, str, str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build solver-ready data structures."""
    if not routes:
        raise ValueError("routes list is empty")
    if not vessels:
        raise ValueError("vessels dict is empty")

    route_ids = [r.route_id for r in routes]
    
    # Sort Corsa IDs chronologically
    corsa_start_map = {}
    for r in routes:
        if r.corsa_id not in corsa_start_map:
            corsa_start_map[r.corsa_id] = r.start_dt
        else:
            corsa_start_map[r.corsa_id] = min(corsa_start_map[r.corsa_id], r.start_dt)

    corsa_ids = sorted(corsa_start_map.keys(), key=lambda cid: (corsa_start_map[cid], cid))
    
    corsa_index = {cid: i for i, cid in enumerate(corsa_ids)}
    route_corsa_idx = [corsa_index[r.corsa_id] for r in routes]
    vessel_ids = sorted(vessels.keys())

    R = len(routes)
    C = len(corsa_ids)
    V = len(vessel_ids)
    START = R
    full_mask = (1 << C) - 1
    INF = float("inf")

    ports = sorted({r.origin for r in routes} | {r.destination for r in routes})
    p2i = {p: i for i, p in enumerate(ports)}

    pickup_time = [r.start_s for r in routes]
    cost_full = [r.consumo for r in routes]
    mu_arr = [r.pax_min for r in routes]
    sigma_arr = [max(1.0, (r.pax_max - r.pax_min) / 4.0) for r in routes]
    corsa_route_mask: List[int] = [0] * C
    for r_i, c_i in enumerate(route_corsa_idx):
        corsa_route_mask[c_i] |= (1 << r_i)

    reposition_lookup = build_reposition_lookup(routes, reposition_view)

    def is_compatible(route: Route, vessel_id: str) -> bool:
        return route.vessel_id is None or route.vessel_id == vessel_id

    # Build reposition matrices per vessel
    rep_dur: Dict[str, List[List[Optional[int]]]] = {}
    rep_cost: Dict[str, List[List[float]]] = {}
    for vid in vessel_ids:
        rep_dur[vid] = [[None] * len(ports) for _ in range(len(ports))]
        rep_cost[vid] = [[INF] * len(ports) for _ in range(len(ports))]
        for p in ports:
            i = p2i[p]
            rep_dur[vid][i][i] = 0
            rep_cost[vid][i][i] = 0.0

        for (o, d, v), (dur_s, cost) in reposition_lookup.items():
            if v != vid:
                continue
            rep_dur[vid][p2i[o]][p2i[d]] = int(dur_s)
            rep_cost[vid][p2i[o]][p2i[d]] = float(cost)

    next_mask: List[List[int]] = [[0] * (R + 1) for _ in range(V)]
    inc_cost: List[List[List[float]]] = [[[INF] * R for _ in range(R + 1)] for _ in range(V)]
    inc_risk: List[List[List[float]]] = [[[INF] * R for _ in range(R + 1)] for _ in range(V)]

    # START -> any
    for v_i, vid in enumerate(vessel_ids):
        allowed_mask = 0
        for r_i, r in enumerate(routes):
            if is_compatible(r, vid):
                allowed_mask |= (1 << r_i)
        next_mask[v_i][START] = allowed_mask
        for r_i in range(R):
            if not ((allowed_mask >> r_i) & 1):
                continue
            inc_cost[v_i][START][r_i] = cost_full[r_i]
            inc_risk[v_i][START][r_i] = prob_overload_normal(mu_arr[r_i], sigma_arr[r_i], vessels[vid].capacity)

    # route -> route
    for v_i, vid in enumerate(vessel_ids):
        for a_i, a in enumerate(routes):
            if not is_compatible(a, vid):
                continue
            bits = 0
            a_end = a.end_s
            a_dest_i = p2i[a.destination]
            for b_i, b in enumerate(routes):
                if b_i == a_i:
                    continue
                if not is_compatible(b, vid):
                    continue
                b_orig_i = p2i[b.origin]
                dur = rep_dur[vid][a_dest_i][b_orig_i]
                if dur is None:
                    continue
                if a_end + dur <= b.start_s:
                    bits |= (1 << b_i)
                    rep_c = rep_cost[vid][a_dest_i][b_orig_i]
                    if rep_c != INF:
                        inc_cost[v_i][a_i][b_i] = rep_c + cost_full[b_i]
                        inc_risk[v_i][a_i][b_i] = prob_overload_normal(mu_arr[b_i], sigma_arr[b_i], vessels[vid].capacity)
            next_mask[v_i][a_i] = bits

    # Lower bounds (per corsa)
    risk_table = [[0.0] * R for _ in range(V)]
    for v_i, vid in enumerate(vessel_ids):
        cap = vessels[vid].capacity
        for r_i in range(R):
            if not is_compatible(routes[r_i], vid):
                risk_table[v_i][r_i] = float("inf")
            else:
                risk_table[v_i][r_i] = prob_overload_normal(mu_arr[r_i], sigma_arr[r_i], cap)

    route_min_risk: List[float] = []
    for r_i in range(R):
        best = min(risk_table[v_i][r_i] for v_i in range(V))
        if best == float("inf"):
            raise ValueError(f"Route {route_ids[r_i]} has no compatible vessels")
        route_min_risk.append(best)
    
    lb_cost: List[float] = [0.0] * C
    lb_risk: List[float] = [0.0] * C
    for c_i in range(C):
        rmask = corsa_route_mask[c_i]
        if rmask == 0:
            raise ValueError(f"corsa_id {corsa_ids[c_i]} has no routes")
        min_cost = float("inf")
        min_risk = float("inf")
        m = rmask
        while m:
            b = m & -m
            r_i = b.bit_length() - 1
            min_cost = min(min_cost, cost_full[r_i])
            min_risk = min(min_risk, route_min_risk[r_i])
            m ^= b
        lb_cost[c_i] = min_cost
        lb_risk[c_i] = min_risk

    # 2^R tables can overflow for large R
    max_lb_states = 1 << 22
    if C >= 63 or (1 << C) > max_lb_states:
        LB_cost = None
        LB_risk = None
    else:
        LB_cost = [0.0] * (1 << C)
        LB_risk = [0.0] * (1 << C)
        LB_cost[0] = float(sum(lb_cost))
        LB_risk[0] = float(sum(lb_risk))
        for m in range(1, 1 << C):
            b = m & -m
            i = (b.bit_length() - 1)
            LB_cost[m] = LB_cost[m ^ b] - lb_cost[i]
            LB_risk[m] = LB_risk[m ^ b] - lb_risk[i]

    return {
        "route_ids": route_ids,
        "routes": routes,
        "route_by_id": {r.route_id: r for r in routes},
        "corsa_ids": corsa_ids,
        "route_corsa_idx": route_corsa_idx,
        "corsa_route_mask": corsa_route_mask,
        "vessel_ids": vessel_ids,
        "R": R,
        "C": C,
        "V": V,
        "START": START,
        "full_mask": full_mask,
        "pickup_time": pickup_time,
        "next_mask": next_mask,
        "inc_cost": inc_cost,
        "inc_risk": inc_risk,
        "risk_table": risk_table,
        "rep_dur": rep_dur,
        "LB_cost": LB_cost,
        "LB_risk": LB_risk,
    }


def leq_vec(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
    return a[0] <= b[0] and a[1] <= b[1]


def pareto_insert_front(front: List[Tuple[float, float, Any]], cand: Tuple[float, float, Any]) -> bool:
    c1, c2, _ = cand
    for e1, e2, _ in front:
        if leq_vec((e1, e2), (c1, c2)):
            return False
    kept = []
    for e1, e2, pl in front:
        if not leq_vec((c1, c2), (e1, e2)):
            kept.append((e1, e2, pl))
    kept.append(cand)
    front[:] = kept
    return True


def solve_pareto_namoa_astar(
    problem: Dict[str, Any],
    route_choice: str = "time_mrv",
    max_solutions: Optional[int] = None,
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    """
    NAMOA* multi-objective solver for scheduling.
    Returns Pareto-optimal solutions minimizing cost and risk.
    """
    R = problem["R"]
    C = problem["C"]
    V = problem["V"]
    START = problem["START"]
    full_mask = problem["full_mask"]

    next_mask = problem["next_mask"]
    inc_cost = problem["inc_cost"]
    inc_risk = problem["inc_risk"]
    LB_cost = problem["LB_cost"]
    LB_risk = problem["LB_risk"]
    route_ids = problem["route_ids"]
    route_by_id = problem["route_by_id"]
    corsa_ids = problem["corsa_ids"]
    route_corsa_idx = problem["route_corsa_idx"]
    corsa_route_mask = problem["corsa_route_mask"]
    vessel_ids = problem["vessel_ids"]
    pickup_time = problem["pickup_time"]

    INF = float("inf")

    state_front: Dict[Tuple[int, Tuple[int, ...]], List[Tuple[float, float, int]]] = {}
    sol_front: List[Tuple[float, float, int]] = []

    labels: Dict[int, Tuple[int, Tuple[int, ...], float, float]] = {}
    active: Dict[int, bool] = {}
    parent: Dict[int, Tuple[int, int, str]] = {}

    def try_add_label(mask: int, lastP: Tuple[int, ...], g1: float, g2: float, lid: int) -> bool:
        rmask = full_mask ^ mask
        reach_sig = tuple(
            bool(next_mask[v_i][lastP[v_i]] & rmask)
            for v_i in range(V))
        
        st = (mask, lastP, reach_sig)
        front = state_front.setdefault(st, [])
        for e1, e2, _ in front:
            if leq_vec((e1, e2), (g1, g2)):
                return False
        kept = []
        for e1, e2, eid in front:
            if not leq_vec((g1, g2), (e1, e2)):
                kept.append((e1, e2, eid))
            else:
                active[eid] = False
        kept.append((g1, g2, lid))
        state_front[st] = kept
        return True

    def pruned_by_solutions(f1: float, f2: float) -> bool:
        for s1, s2, _ in sol_front:
            if s1 <= f1 and s2 <= f2:
                return True
        return False

    def choose_next_route(corsa_mask: int, lastP: Tuple[int, ...]) -> Optional[int]:
        remaining = full_mask ^ corsa_mask
        if remaining == 0:
            return None
    
        c_i = (remaining & -remaining).bit_length() - 1
        rmask = corsa_route_mask[c_i]
    
        best = None
        best_deg = INF
    
        m = rmask
        while m:
            b = m & -m
            r_i = b.bit_length() - 1
    
            deg = 0
            for v_i in range(V):
                if (next_mask[v_i][lastP[v_i]] >> r_i) & 1:
                    deg += 1
    
            if deg > 0 and deg < best_deg:
                best_deg = deg
                best = r_i
    
            m ^= b
    
        return best

    START_LAST = tuple([START] * V)
    lid0 = 0
    labels[lid0] = (0, START_LAST, 0.0, 0.0)
    active[lid0] = True
    state_front[(0, START_LAST)] = [(0.0, 0.0, lid0)]

    pq = []
    f10 = LB_cost[0] if LB_cost is not None else 0.0
    f20 = LB_risk[0] if LB_risk is not None else 0.0
    heapq.heappush(pq, (f10, f20, 0.0, 0.0, lid0, 0, START_LAST))

    while pq:
        f1, f2, g1, g2, lid, mask, lastP = heapq.heappop(pq)
        if not active.get(lid, False):
            continue

        cur = labels.get(lid)
        if cur is None:
            continue
        mask2, lastP2, gg1, gg2 = cur
        if mask2 != mask or lastP2 != lastP or gg1 != g1 or gg2 != g2:
            continue

        if pruned_by_solutions(f1, f2):
            continue

        if mask == full_mask:
            inserted = pareto_insert_front(sol_front, (g1, g2, lid))
            if inserted and max_solutions is not None and len(sol_front) >= max_solutions:
                break
            continue

        remaining_corsa = full_mask ^ mask

        # If any remaining corsa has no reachable route, prune
        infeasible = False
        for c_i in range(C):
            if (remaining_corsa >> c_i) & 1 == 0:
                continue
        
            feasible_for_corsa = False
            rmask = corsa_route_mask[c_i]
        
            for v_i in range(V):
                if (next_mask[v_i][lastP[v_i]] & rmask) != 0:
                    feasible_for_corsa = True
                    break
        
            if not feasible_for_corsa:
                infeasible = True
                break
        
        if infeasible:
            continue

        r_idx = choose_next_route(mask, lastP)
        if r_idx is None:
            continue

        bit = 1 << r_idx
        new_mask = mask | (1 << route_corsa_idx[r_idx])

        for v_i in range(V):
            last_idx = lastP[v_i]
            if (next_mask[v_i][last_idx] & bit) == 0:
                continue

            dc = inc_cost[v_i][last_idx][r_idx]
            dr = inc_risk[v_i][last_idx][r_idx]
            if dc == INF or dr == INF:
                continue

            ng1 = g1 + dc
            ng2 = g2 + dr

            lb1 = LB_cost[new_mask] if LB_cost is not None else 0.0
            lb2 = LB_risk[new_mask] if LB_risk is not None else 0.0
            nf1 = ng1 + lb1
            nf2 = ng2 + lb2
            if pruned_by_solutions(nf1, nf2):
                continue

            new_last = list(lastP)
            new_last[v_i] = r_idx
            new_last_t = tuple(new_last)

            lid2 = len(labels) + 1
            labels[lid2] = (new_mask, new_last_t, ng1, ng2)
            active[lid2] = True

            if not try_add_label(new_mask, new_last_t, ng1, ng2, lid2):
                active[lid2] = False
                continue

            parent[lid2] = (lid, v_i, route_ids[r_idx])
            heapq.heappush(pq, (nf1, nf2, ng1, ng2, lid2, new_mask, new_last_t))

    # Build solutions
    solutions: List[Dict[str, Any]] = []
    for cost, risk, lid_goal in sorted(sol_front, key=lambda x: (x[0], x[1])):
        plan = {v: [] for v in vessel_ids}
        cur_id = lid_goal
        while cur_id in parent:
            prev_id, v_i, rid = parent[cur_id]
            plan[vessel_ids[v_i]].append(route_by_id[rid])
            cur_id = prev_id
        for v in plan:
            plan[v].reverse()
        solutions.append({"cost": cost, "risk": risk, "plan": {k: v for k, v in plan.items() if v}})

    return solutions


def prepara_riposizionamenti(
    routes: List[Route],
    *,
    exclude_same_port: bool = True,
) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """
    Build valid reposition arcs BETWEEN routes i -> j.
    """
    risultati: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for a in routes:
        for b in routes:
            if a is b:
                continue
            if a.vessel_id != b.vessel_id:
                continue

            if exclude_same_port and a.destination == b.origin:
                continue

            # must be temporally feasible
            if a.end_dt >= b.start_dt:
                continue

            dur_min = (b.start_dt - a.end_dt).total_seconds() / 60.0
            if dur_min <= 0:
                continue

            key = (a.destination, b.origin, a.vessel_id)

            # keep best (shortest) reposition
            if key not in risultati or dur_min < risultati[key]["tempo_riposizionamento"]:
                risultati[key] = {
                    "tempo_riposizionamento": dur_min,
                    "consumo_riposizionamento": max(0.1, dur_min * 0.05),
                }

    return risultati

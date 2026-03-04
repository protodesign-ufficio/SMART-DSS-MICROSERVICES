import heapq
from typing import Dict, Tuple, List, Callable
from collections import deque
import math
import numpy as np

Cost = Tuple[float, float]
Node = Tuple[int, int]  # oppure qualunque hashable (str, int, tuple, ...)

# def dominates(a: Cost, b: Cost) -> bool:
#     """True se costo a domina b (<= componente per componente e < in almeno una)."""
#     return (a[0] <= b[0] and a[1] <= b[1]) and (a[0] < b[0] or a[1] < b[1])

def dominates(a: Cost, b: Cost, eps_time: float = 0.0, eps_energy: float = 0.0) -> bool:
    """
    ε-dominanza:
    se eps == 0 → dominanza classica (stretta su almeno una componente)
    se eps != 0 → basta il confronto rilassato
    """

    cond_leq = (
        a[0] <= b[0] + eps_time and
        a[1] <= b[1] + eps_energy
    )

    # if eps_time != 0.0 or eps_energy != 0.0:
    #     return cond_leq

    cond_strict = (
        a[0] < b[0] or
        a[1] < b[1]
    )

    return cond_leq and cond_strict



def is_dominated_by_any(x: Cost, costs: List[Cost], eps_time: float, eps_energy: float) -> bool:
    """True se x è dominato da almeno un costo in 'costs'."""
    for c in costs:
        if dominates(c, x, eps_time, eps_energy):
            return True
    return False

import math
tol = 1e-9  # tolleranza per confronto float
def insert_nondominated(label_set: List[Cost], x: Cost, eps_time: float, eps_energy: float) -> bool:
    """
    Inserisce x in label_set se non dominato.
    Rimuove eventuali label dominate da x.
    Ritorna True se x è stato inserito (altrimenti False).
    """
    # se già dominato, scarto
    for c in label_set:
        if dominates(c, x, eps_time, eps_energy) or (math.isclose(c[0], x[0], abs_tol=tol) and math.isclose(c[1], x[1], abs_tol=tol)):
            return False
    # rimuovo quelle dominate da x
    keep = []
    for c in label_set:
        if not dominates(x, c, eps_time, eps_energy):
            keep.append(c)
    keep.append(x)
    label_set[:] = keep
    return True

def reconstruct_path(
    parents: Dict[Tuple[Node, Cost], Tuple[Node, Cost, str]],
    goal: Node,
    goal_cost: Cost,
    start: Node
) -> Tuple[List[Node], List[str]]:
    """Risale i parents restituendo path + lista tipi arco (in parallelo)."""
    path: List[Node] = [goal]
    types: List[str] = []
    cur_key = (goal, goal_cost)  # <-- la chiave è sempre (node, cost)

    while cur_key in parents:
        prev_node, prev_cost, tipo = parents[cur_key]
        path.append(prev_node)
        types.append(tipo)
        cur_key = (prev_node, prev_cost)  # <-- torna a una chiave (node, cost)
        if prev_node == start:
            break

    path.reverse()
    types.reverse()
    return path, types



def zero_heuristic(_: Node) -> Cost:
    """Heuristica nulla: (0,0)."""
    return (0.0, 0.0)


def namoa_instrumented(
    graph,
    start,
    goal,
    heuristic=zero_heuristic,
    cost_round=2,
    t_max=float("inf"),
    log_every=50,
    eps_time=0.0,
    eps_cost=0.0
):
    import heapq, math
    #CALCOLO EPS_TIME A MANO
    t_min = 0
    t_max_eps = 100
    n_int = 25
    n_sol_int = 5
    delta_t = (t_max_eps - t_min)/n_int
    eps_time = delta_t
    #eps_cost = eps_time
    #eps_time = 0.0
    eps_cost = 0.0
    print(f"[NAMOA* INSTRUMENTED] eps_time calcolato: {eps_time}")

    #n, delta, L, S = estimate_exhaustive_iterations_upper_bound(graph, start)
    # print(f"[EXHAUSTIVE UB] reachable_n={n}, delta={delta}, L={L} => iterations_upper_bound={S}")

    def norm(cost):
        return (round(cost[0], cost_round), round(cost[1], cost_round))

    # --- strutture NAMOA ---
    labels = {u: [] for u in graph}
    labels[start] = [norm((0.0, 0.0))]

    parents = {}
    goal_labels = []
    open_heap = []

    g0 = norm((0.0, 0.0))
    h0 = heuristic(start)
    f0 = norm((g0[0] + h0[0], g0[1] + h0[1]))
    heapq.heappush(open_heap, (f0[0], f0[1], g0[0], g0[1], start))

    solutions = []

    # --- contatori ---
    expanded = 0
    popped = 0
    pruned_local = 0
    pruned_goal = 0
    dead_on_pop = 0

    # --- log ---
    log = []
    
    log.append({
        "expanded": 0,
        "open": len(open_heap),
        "labels": sum(len(v) for v in labels.values()),
        "goal_labels": len(goal_labels),
        "prune_local": 0,
        "prune_goal": 0,
        "dead_ratio": 0.0,
        "max_labels_node": max((len(v) for v in labels.values()), default=0)

    })

    while open_heap:
        popped += 1
        f1, f2, g1, g2, u = heapq.heappop(open_heap)
        g_u = norm((g1, g2))

        # pruning locale
        if is_dominated_by_any(g_u, labels[u], eps_time, eps_cost):
            pruned_local += 1
            dead_on_pop += 1
            continue

        # pruning globale
        if is_dominated_by_any(g_u, goal_labels, eps_time, eps_cost):
            pruned_goal += 1
            dead_on_pop += 1
            continue

        expanded += 1


        # --- logging ---
        if expanded % log_every == 0:
            labels_tot = sum(len(v) for v in labels.values())
            log.append({
                "expanded": expanded,
                "open": len(open_heap),
                "labels": labels_tot,
                "goal_labels": len(goal_labels),
                "prune_local": pruned_local,
                "prune_goal": pruned_goal,
                "dead_ratio": dead_on_pop / max(1, popped),
                "max_labels_node": max(len(v) for v in labels.values())
            })

        # --- goal ---
        if u == goal:
            if insert_nondominated(goal_labels, g_u, eps_time, eps_cost):
                path, types = reconstruct_path(parents, goal, g_u, start)
                solutions.append((g_u, path, types))
            continue

        # --- espansione ---
        for edge in graph[u]:
            #print("Edge:", edge, "in nodo:", u)
            if len(edge) == 3:
                v, dt, dc = edge
                tipo = None
            else:
                v, dt, dc, tipo = edge

            g_v = norm((g_u[0] + dt, g_u[1] + dc))

            # scarta costi invalidi
            if math.isnan(g_v[0]) or math.isnan(g_v[1]):
                continue

            if g_v[0] > t_max:
                continue

            if is_dominated_by_any(g_v, goal_labels, eps_time, eps_cost):
                pruned_goal += 1
                continue

            if not insert_nondominated(labels[v], g_v, eps_time, eps_cost):
                pruned_local += 1
                continue

            parents[(v, g_v)] = (u, g_u, tipo)

            h_v = heuristic(v)
            f_v = norm((g_v[0] + h_v[0], g_v[1] + h_v[1]))
            heapq.heappush(open_heap, (f_v[0], f_v[1], g_v[0], g_v[1], v))

    solutions.sort(key=lambda x: (x[0][0], x[0][1]))
    return solutions, log


def reachable_nodes(graph, start):
    q = deque([start])
    seen = {start}
    while q:
        u = q.popleft()
        for edge in graph.get(u, []):
            v = edge[0]  # v è sempre il primo elemento (v, dt, dc, ...)
            if v not in seen:
                seen.add(v)
                q.append(v)
    return seen

def estimate_exhaustive_iterations_upper_bound(graph, start, goal=None):
    # 1) nodi raggiungibili da start
    R = reachable_nodes(graph, start)
    n = len(R)

    # 2) delta = massimo out-degree sui raggiungibili
    delta = 0
    for u in R:
        #print("Nodo raggiungibile:", u, "out-degree:", len(graph.get(u, [])))
        delta = max(delta, len(graph.get(u, [])))

    # 3) no-revisit => lunghezza max cammino semplice <= n-1
    L = max(0, n - 1)

    # 4) upper bound S(L)
    if L == 0:
        S = 1
    elif delta == 0:
        S = 1
    elif delta == 1:
        # al massimo una scelta ogni step
        S = 1 + L
    elif delta == 2:
        # 1 + 2L (perché (delta-1)=1)
        S = 1 + 2 * L
    else:
        # 1 + delta * ((delta-1)^L - 1) / (delta-2)
        S = 1 + delta * (((delta - 1) ** L - 1) // (delta - 2))

    return n, delta, L, S

import math

def reverse_graph(graph):
    G_rev = {u: [] for u in graph}
    for u, edges in graph.items():
        for edge in edges:
            if len(edge) == 3:
                v, dt, dc = edge
                tipo = None
            else:
                v, dt, dc, tipo = edge
            G_rev[v].append((u, dt, dc, tipo))
    return G_rev

import heapq

def dijkstra_single_cost(graph, source, idx):
    dist = {u: float("inf") for u in graph}
    dist[source] = 0.0
    heap = [(0.0, source)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for edge in graph[u]:
            v = edge[0]
            cost = edge[1 + idx]  # idx=0 tempo, idx=1 consumo
            nd = d + cost
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist

def namoa_instrumented_visual(
    graph,
    start,
    goal,
    heuristic=zero_heuristic,
    cost_round=3,
    t_max=float("inf"),
    log_every=50,
    step_every=1,          # aggiorna grafico ogni N espansioni (1 = ogni espansione)
    pause=0.05,            # pausa matplotlib tra i frame
    show_edge_checks=True, # mostra feedback per ogni arco valutato
    max_edge_notes=30,     # limita quante annotazioni scrivere per step
    pos_fn=None            # funzione pos_fn(node)->(x,y). default: node=(x,y)
):
    """
    Copia fedele di namoa_instrumented + visualizzazione live.

    NOTE:
    - richiede Node tipicamente tuple (x,y) oppure fornire pos_fn.
    - usa matplotlib in modalità interattiva (plt.ion()).
    """

    import heapq, math
    import matplotlib.pyplot as plt

    # ---- helper posizione ----
    if pos_fn is None:
        def pos_fn(n):
            # default: Node = (x,y)
            return (n[0], n[1])

    # ---- la tua norm identica ----
    def norm(cost):
        return (round(cost[0], cost_round), round(cost[1], cost_round))

    # ---- strutture identiche alla tua namoa_instrumented ----
    labels = {u: [] for u in graph}
    labels[start] = [norm((0.0, 0.0))]

    parents = {}
    goal_labels = []
    open_heap = []

    g0 = norm((0.0, 0.0))
    h0 = heuristic(start)
    f0 = norm((g0[0] + h0[0], g0[1] + h0[1]))
    heapq.heappush(open_heap, (f0[0], f0[1], g0[0], g0[1], start))

    solutions = []

    expanded = 0
    popped = 0
    pruned_local = 0
    pruned_goal = 0
    dead_on_pop = 0

    log = []
    log.append({
        "expanded": 0,
        "open": len(open_heap),
        "labels": sum(len(v) for v in labels.values()),
        "goal_labels": len(goal_labels),
        "prune_local": 0,
        "prune_goal": 0,
        "dead_ratio": 0.0,
        "max_labels_node": max((len(v) for v in labels.values()), default=0)
    })

    # ---- VIS: setup figura ----
    plt.ion()
    fig, ax = plt.subplots(figsize=(12, 7))

    all_nodes = list(graph.keys())
    xs = []
    ys = []
    for n in all_nodes:
        x, y = pos_fn(n)
        xs.append(x); ys.append(y)

    # base scatter
    base_sc = ax.scatter(xs, ys, s=12)

    sx, sy = pos_fn(start)
    gx, gy = pos_fn(goal)

    start_sc = ax.scatter([sx], [sy], marker="*", s=220, label="Start")
    goal_sc  = ax.scatter([gx], [gy], marker="X", s=180, label="Goal")

    # overlay dinamici
    popped_sc   = ax.scatter([], [], s=90, marker="o", label="Popped label node")
    expanded_sc = ax.scatter([], [], s=130, marker="s", label="Expanded label node")
    open_sc     = ax.scatter([], [], s=25, marker=".", label="Open nodes (unique)")

    # linee del path corrente
    path_line, = ax.plot([], [], linewidth=2)

    # testo status
    status_text = ax.text(
        0.02, 0.98, "", transform=ax.transAxes, va="top", ha="left"
    )

    # annotazioni per edge-check (pulite ogni step)
    edge_text_artists = []

    ax.legend(loc="upper right")
    ax.set_title("NAMOA*: live debug (pops/expansions/pruning/path)")
    ax.grid(True)

    # ---- helper per aggiornare gli overlay ----
    def clear_edge_notes():
        nonlocal edge_text_artists
        for t in edge_text_artists:
            try:
                t.remove()
            except Exception:
                pass
        edge_text_artists = []

    def update_open_overlay():
        # open_heap contiene molte label per stesso nodo: mostro nodi unici
        uniq = set()
        for (_, _, _, _, node) in open_heap:
            uniq.add(node)
        ox = []; oy = []
        for n in uniq:
            x, y = pos_fn(n)
            ox.append(x); oy.append(y)
        open_sc.set_offsets(list(zip(ox, oy)) if ox else np.empty((0, 2)))

    def update_path_overlay(path_nodes):
        if not path_nodes or len(path_nodes) < 2:
            path_line.set_data([], [])
            return
        px = []; py = []
        for n in path_nodes:
            x, y = pos_fn(n)
            px.append(x); py.append(y)
        path_line.set_data(px, py)

    # ---- ciclo identico + hook VIS ----
    while open_heap:
        popped += 1
        f1, f2, g1, g2, u = heapq.heappop(open_heap)
        g_u = norm((g1, g2))

        # VIS: nodo poppato
        ux, uy = pos_fn(u)
        popped_sc.set_offsets([(ux, uy)])

        # pruning locale (identico)
        if is_dominated_by_any(g_u, labels[u]):
            pruned_local += 1
            dead_on_pop += 1

            # VIS: status e update open
            if (popped % step_every) == 0:
                expanded_sc.set_offsets(np.empty((0, 2)))  # niente espansione
                update_open_overlay()
                update_path_overlay([])

                status_text.set_text(
                    f"POP #{popped}  EXP #{expanded}\n"
                    f"u={u} g={g_u} f=({f1},{f2})\n"
                    f"PRUNE_LOCAL on pop\n"
                    f"open={len(open_heap)} labels_tot={sum(len(v) for v in labels.values())}\n"
                    f"prune_local={pruned_local} prune_goal={pruned_goal} dead_ratio={dead_on_pop/max(1,popped):.3f}\n"
                    f"goal_labels={len(goal_labels)}"
                )
                fig.canvas.draw_idle()
                plt.pause(pause)
            continue

        # pruning globale (identico)
        if is_dominated_by_any(g_u, goal_labels):
            pruned_goal += 1
            dead_on_pop += 1

            # VIS: status e update open
            if (popped % step_every) == 0:
                expanded_sc.set_offsets(np.empty((0, 2)))
                update_open_overlay()
                update_path_overlay([])

                status_text.set_text(
                    f"POP #{popped}  EXP #{expanded}\n"
                    f"u={u} g={g_u} f=({f1},{f2})\n"
                    f"PRUNE_GOAL on pop\n"
                    f"open={len(open_heap)} labels_tot={sum(len(v) for v in labels.values())}\n"
                    f"prune_local={pruned_local} prune_goal={pruned_goal} dead_ratio={dead_on_pop/max(1,popped):.3f}\n"
                    f"goal_labels={len(goal_labels)}"
                )
                fig.canvas.draw_idle()
                plt.pause(pause)
            continue

        # ora è un'espansione reale (identico)
        expanded += 1

        # logging identico
        if expanded % log_every == 0:
            labels_tot = sum(len(v) for v in labels.values())
            log.append({
                "expanded": expanded,
                "open": len(open_heap),
                "labels": labels_tot,
                "goal_labels": len(goal_labels),
                "prune_local": pruned_local,
                "prune_goal": pruned_goal,
                "dead_ratio": dead_on_pop / max(1, popped),
                "max_labels_node": max(len(v) for v in labels.values())
            })

        # VIS: nodo espanso e path corrente (se ricostruibile)
        if (expanded % step_every) == 0:
            expanded_sc.set_offsets([(ux, uy)])
            update_open_overlay()

            # prova a ricostruire path corrente della label (u,g_u) se ha parents
            cur_path = []
            try:
                # ricostruisco “fino a u” usando lo stesso reconstruct_path,
                # ma serve un goal: qui uso u come goal temporaneo
                cur_path, _types = reconstruct_path(parents, u, g_u, start)
            except Exception:
                cur_path = []
            update_path_overlay(cur_path)

            clear_edge_notes()
            status_text.set_text(
                f"POP #{popped}  EXP #{expanded}\n"
                f"EXPAND u={u} g={g_u} f=({f1},{f2})\n"
                f"open={len(open_heap)} labels_tot={sum(len(v) for v in labels.values())}\n"
                f"prune_local={pruned_local} prune_goal={pruned_goal} dead_ratio={dead_on_pop/max(1,popped):.3f}\n"
                f"goal_labels={len(goal_labels)}"
            )
            fig.canvas.draw_idle()
            plt.pause(pause)

        # goal-case identico
        if u == goal:
            if insert_nondominated(goal_labels, g_u):
                path, types = reconstruct_path(parents, goal, g_u, start)
                solutions.append((g_u, path, types))

                # VIS: se trovi soluzione, mostra path soluzione
                if (expanded % step_every) == 0:
                    update_path_overlay(path)
                    status_text.set_text(
                        status_text.get_text()
                        + "\nNEW PARETO SOLUTION at GOAL\n"
                        + f"g={g_u}  depth={len(path)-1}"
                    )
                    fig.canvas.draw_idle()
                    plt.pause(pause)
            continue

        # espansione archi identica (+ note VIS)
        edge_note_count = 0
        for edge in graph[u]:
            if len(edge) == 3:
                v, dt, dc = edge
                tipo = None
            else:
                v, dt, dc, tipo = edge

            g_v = norm((g_u[0] + dt, g_u[1] + dc))

            verdict = None

            # scarta costi invalidi (identico)
            if math.isnan(g_v[0]) or math.isnan(g_v[1]):
                verdict = "NAN"
                # nessun counter nel tuo codice per NAN
                if show_edge_checks and (expanded % step_every) == 0 and edge_note_count < max_edge_notes:
                    vx, vy = pos_fn(v)
                    edge_text_artists.append(ax.text(vx, vy, verdict, fontsize=8))
                    edge_note_count += 1
                continue

            if g_v[0] > t_max:
                verdict = "TMAX"
                if show_edge_checks and (expanded % step_every) == 0 and edge_note_count < max_edge_notes:
                    vx, vy = pos_fn(v)
                    edge_text_artists.append(ax.text(vx, vy, verdict, fontsize=8))
                    edge_note_count += 1
                continue

            if is_dominated_by_any(g_v, goal_labels):
                pruned_goal += 1
                verdict = "PRUNE_GOAL"
                if show_edge_checks and (expanded % step_every) == 0 and edge_note_count < max_edge_notes:
                    vx, vy = pos_fn(v)
                    edge_text_artists.append(ax.text(vx, vy, verdict, fontsize=8))
                    edge_note_count += 1
                continue

            if not insert_nondominated(labels[v], g_v):
                pruned_local += 1
                verdict = "PRUNE_LOCAL"
                if show_edge_checks and (expanded % step_every) == 0 and edge_note_count < max_edge_notes:
                    vx, vy = pos_fn(v)
                    edge_text_artists.append(ax.text(vx, vy, verdict, fontsize=8))
                    edge_note_count += 1
                continue

            # ACCEPT identico
            parents[(v, g_v)] = (u, g_u, tipo)

            h_v = heuristic(v)
            f_v = norm((g_v[0] + h_v[0], g_v[1] + h_v[1]))
            heapq.heappush(open_heap, (f_v[0], f_v[1], g_v[0], g_v[1], v))

            verdict = "ACCEPT"
            if show_edge_checks and (expanded % step_every) == 0 and edge_note_count < max_edge_notes:
                vx, vy = pos_fn(v)
                edge_text_artists.append(ax.text(vx, vy, verdict, fontsize=8))
                edge_note_count += 1

        # VIS: dopo aver processato gli archi, refresh open overlay
        if (expanded % step_every) == 0:
            update_open_overlay()
            fig.canvas.draw_idle()
            plt.pause(pause)

    solutions.sort(key=lambda x: (x[0][0], x[0][1]))
    return solutions, log


def build_time_min_graph(graph):
    """
    Per ogni (u,v) mantiene solo l'arco con dt minimo
    """
    Gt = {}

    for u, edges in graph.items():
        best = {}  # v -> (dt, edge)
        for edge in edges:
            v = edge[0]
            dt = edge[1]

            if v not in best or dt < best[v][0]:
                best[v] = (dt, edge)

        Gt[u] = [best[v][1] for v in best]

    return Gt

import heapq

def dijkstra_time_from_start(graph, start):
    dist = {u: float("inf") for u in graph}
    dist[start] = 0.0
    heap = [(0.0, start)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue

        for edge in graph[u]:
            v = edge[0]
            dt = edge[1]      # tempo
            nd = d + dt

            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(heap, (nd, v))

    return dist

def filter_graph_by_reachable(graph, reachable):
    """
    Ritorna un sottografo che contiene solo:
    - nodi in reachable
    - archi che puntano a nodi in reachable
    """
    new_graph = {}

    for u in reachable:
        if u not in graph:
            continue

        new_edges = []
        for edge in graph[u]:
            v = edge[0]
            if v in reachable:
                new_edges.append(edge)

        new_graph[u] = new_edges

    return new_graph

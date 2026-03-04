#!/usr/bin/env python3
"""
Scheduler Service - Fleet scheduling optimization with NAMOA* algorithm.
"""
from flask import Flask, request, jsonify
from typing import Any, Dict, List

from models import Route, Vessel, parse_datetime
from solver import build_problem, solve_pareto_namoa_astar, prepara_riposizionamenti

app = Flask(__name__)


def route_to_dict(r: Route) -> Dict[str, Any]:
    """Convert Route dataclass to JSON-serializable dict."""
    return {
        "route_id": r.route_id,
        "corsa_id": r.corsa_id,
        "corsa_name": r.corsa_name,
        "vessel_id": r.vessel_id,
        "vessel_name": r.vessel_name,
        "capacity": r.capacity,
        "origin": r.origin,
        "destination": r.destination,
        "start_dt": r.start_dt.isoformat(),
        "end_dt": r.end_dt.isoformat(),
        "consumo": r.consumo,
        "comfort": r.comfort,
        "pax_min": r.pax_min,
        "pax_max": r.pax_max
    }


def build_detailed_plan(solutions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build detailed plan with repositioning and wait activities.
    Similar to report_plan_with_repositioning but returns dict instead of DataFrame.
    """
    detailed_solutions = []

    for sol_i, sol in enumerate(solutions):
        plan = sol.get("plan", {})
        activities = []
        
        for vid, routes in plan.items():
            if not routes:
                continue
                
            # Sort routes by time
            routes_sorted = sorted(routes, key=lambda r: r.start_dt)
            
            for i, current_route in enumerate(routes_sorted):
                # Add the actual commercial route (trip)
                activities.append({
                    "solution_id": sol_i,
                    "vessel_id": current_route.vessel_id,
                    "vessel_name": current_route.vessel_name,
                    "type": "TRIP",
                    "detail": current_route.corsa_name,
                    "route_id": current_route.route_id,
                    "corsa_id": current_route.corsa_id,
                    "origin": current_route.origin,
                    "destination": current_route.destination,
                    "start_dt": current_route.start_dt.isoformat(),
                    "end_dt": current_route.end_dt.isoformat(),
                    "duration_min": (current_route.end_dt - current_route.start_dt).total_seconds() / 60,
                    "cost": current_route.consumo
                })

                # Calculate the gap to the next route (if exists)
                if i < len(routes_sorted) - 1:
                    next_route = routes_sorted[i+1]
                    
                    gap_start = current_route.end_dt
                    gap_end = next_route.start_dt
                    gap_duration = (gap_end - gap_start).total_seconds() / 60
                    
                    if current_route.destination != next_route.origin:
                        # REPOSITIONING (empty trip)
                        activities.append({
                            "solution_id": sol_i,
                            "vessel_id": current_route.vessel_id,
                            "vessel_name": current_route.vessel_name,
                            "type": "REPOSITION",
                            "detail": f"Empty: {current_route.destination} -> {next_route.origin}",
                            "route_id": None,
                            "corsa_id": None,
                            "origin": current_route.destination,
                            "destination": next_route.origin,
                            "start_dt": gap_start.isoformat(),
                            "end_dt": gap_end.isoformat(),
                            "duration_min": gap_duration,
                            "cost": 0.0
                        })
                    elif gap_duration > 1:  # tolerance for float math
                        # WAITING
                        activities.append({
                            "solution_id": sol_i,
                            "vessel_id": current_route.vessel_id,
                            "vessel_name": current_route.vessel_name,
                            "type": "WAIT",
                            "detail": f"Idle at {current_route.destination}",
                            "route_id": None,
                            "corsa_id": None,
                            "origin": current_route.destination,
                            "destination": current_route.destination,
                            "start_dt": gap_start.isoformat(),
                            "end_dt": gap_end.isoformat(),
                            "duration_min": gap_duration,
                            "cost": 0.0
                        })
        
        # Build plan dict with vessel_id -> list of route dicts
        plan_dict = {}
        for vid, routes in plan.items():
            plan_dict[vid] = [route_to_dict(r) for r in routes]
        
        detailed_solutions.append({
            "solution_id": sol_i,
            "cost": sol["cost"],
            "risk": sol["risk"],
            "plan": plan_dict,
            "activities": activities
        })

    return detailed_solutions


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "scheduler"})


@app.route("/schedule", methods=["POST"])
def schedule():
    """
    Main scheduling endpoint.
    
    Request body:
    {
        "routes": [
            {
                "route_id": "...",
                "corsa_id": "...",
                "corsa_name": "...",
                "vessel_id": "...",
                "vessel_name": "...",
                "capacity": 100,
                "origin": "porto_a_id",
                "destination": "porto_b_id",
                "start_dt": "2026-02-05T08:00:00",
                "end_dt": "2026-02-05T09:00:00",
                "consumo": 10.5,
                "comfort": 0.8,
                "pax_min": 50,
                "pax_max": 80
            },
            ...
        ],
        "vessels": [
            {
                "vessel_id": "...",
                "name": "...",
                "capacity": 100
            },
            ...
        ],
        "max_solutions": 5,
        "include_details": true
    }
    
    Response:
    {
        "status": "ok",
        "solutions": [
            {
                "solution_id": 0,
                "cost": 123.45,
                "risk": 0.05,
                "plan": {
                    "vessel_id_1": [...routes...],
                    ...
                },
                "activities": [...detailed activities...]
            },
            ...
        ]
    }
    """
    try:
        payload = request.get_json(force=True)
        
        # Parse routes
        routes_data = payload.get("routes", [])
        if not routes_data:
            return jsonify({"status": "error", "message": "No routes provided"}), 400
        
        routes: List[Route] = []
        for rd in routes_data:
            routes.append(Route(
                route_id=rd["route_id"],
                corsa_id=rd["corsa_id"],
                corsa_name=rd.get("corsa_name"),
                vessel_id=rd["vessel_id"],
                vessel_name=rd.get("vessel_name"),
                capacity=float(rd["capacity"]),
                origin=rd["origin"],
                destination=rd["destination"],
                start_dt=parse_datetime(rd["start_dt"]),
                end_dt=parse_datetime(rd["end_dt"]),
                consumo=float(rd["consumo"]),
                comfort=float(rd.get("comfort", 0.0)),
                pax_min=float(rd.get("pax_min", 0)),
                pax_max=float(rd.get("pax_max", rd.get("pax_min", 0)))
            ))
        
        # Parse vessels
        vessels_data = payload.get("vessels", [])
        if not vessels_data:
            return jsonify({"status": "error", "message": "No vessels provided"}), 400
        
        vessels: Dict[str, Vessel] = {}
        for vd in vessels_data:
            vid = vd["vessel_id"]
            vessels[vid] = Vessel(
                vessel_id=vid,
                name=vd.get("name", ""),
                capacity=float(vd["capacity"])
            )
        
        # Get options
        max_solutions = payload.get("max_solutions", 5)
        include_details = payload.get("include_details", True)
        
        # Build problem and solve
        reposition_view = prepara_riposizionamenti(routes)
        problem = build_problem(routes, vessels, reposition_view=reposition_view)
        solutions = solve_pareto_namoa_astar(
            problem,
            route_choice="time_mrv",
            max_solutions=max_solutions,
            verbose=False
        )
        
        if not solutions:
            return jsonify({
                "status": "ok",
                "solutions": [],
                "message": "No feasible solutions found"
            })
        
        # Format response
        if include_details:
            response_solutions = build_detailed_plan(solutions)
        else:
            # Simple response with just cost/risk and plan
            response_solutions = []
            for sol_i, sol in enumerate(solutions):
                plan_dict = {}
                for vid, routes in sol["plan"].items():
                    plan_dict[vid] = [route_to_dict(r) for r in routes]
                response_solutions.append({
                    "solution_id": sol_i,
                    "cost": sol["cost"],
                    "risk": sol["risk"],
                    "plan": plan_dict
                })
        
        return jsonify({
            "status": "ok",
            "solutions": response_solutions
        })
        
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Internal error: {str(e)}"}), 500


@app.route("/schedule/validate", methods=["POST"])
def validate_schedule():
    """
    Validate a schedule without running full optimization.
    Useful for checking if input data is correctly formatted.
    """
    try:
        payload = request.get_json(force=True)
        
        routes_data = payload.get("routes", [])
        vessels_data = payload.get("vessels", [])
        
        errors = []
        
        if not routes_data:
            errors.append("No routes provided")
        
        if not vessels_data:
            errors.append("No vessels provided")
        
        # Validate routes
        for i, rd in enumerate(routes_data):
            required_fields = ["route_id", "corsa_id", "vessel_id", "origin", "destination", 
                             "start_dt", "end_dt", "consumo", "capacity"]
            for field in required_fields:
                if field not in rd:
                    errors.append(f"Route {i}: missing required field '{field}'")
            
            if "start_dt" in rd and "end_dt" in rd:
                try:
                    start = parse_datetime(rd["start_dt"])
                    end = parse_datetime(rd["end_dt"])
                    if start >= end:
                        errors.append(f"Route {i}: start_dt must be before end_dt")
                except ValueError as e:
                    errors.append(f"Route {i}: {str(e)}")
        
        # Validate vessels
        for i, vd in enumerate(vessels_data):
            if "vessel_id" not in vd:
                errors.append(f"Vessel {i}: missing vessel_id")
            if "capacity" not in vd:
                errors.append(f"Vessel {i}: missing capacity")
        
        if errors:
            return jsonify({
                "status": "invalid",
                "errors": errors
            }), 400
        
        return jsonify({
            "status": "valid",
            "routes_count": len(routes_data),
            "vessels_count": len(vessels_data)
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    print("[SCHEDULER] Starting scheduler service on port 8091...")
    app.run(host="0.0.0.0", port=8091, debug=False)

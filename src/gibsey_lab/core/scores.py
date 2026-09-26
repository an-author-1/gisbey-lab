"""Validated, provider-free movement rules shared by Core, replay and simulation."""
from __future__ import annotations

import copy

from . import identity

CONTRACT = "score/1"
TERMINAL_STATUSES = ("complete", "ended_by_reader", "exited")
GLOBAL_ACTIONS = ("pause", "resume", "end_journey", "exit")


class ScoreError(ValueError):
    pass


def neutral_score() -> dict:
    return {
        "schema_version": 1, "score_id": "neutral", "score_version": 1,
        "entry_version": None, "initial_movement": "open",
        "global_actions": list(GLOBAL_ACTIONS),
        "relocation": {"permitted": True, "advances": False}, "evidence": "assessed",
        "movements": {"open": {"allowed_functions": ["Q"], "allowed_operators": list(identity.OPERATORS),
                                "guards": [], "advance_after": None, "advance_on": ["Q"], "next": None}},
        "terminal_movements": [], "empty_offer_behavior": "blocked_with_explanation",
    }


def _keys(value, required: set, context: str) -> None:
    if not isinstance(value, dict) or set(value) != required:
        raise ScoreError(f"{context}: expected exactly {sorted(required)}")


def _choices(value, allowed, context: str, *, empty: bool = False) -> None:
    if (not isinstance(value, list) or (not empty and not value)
            or any(not isinstance(item, str) or item not in allowed for item in value)
            or len(value) != len(set(value))):
        raise ScoreError(f"{context}: expected unique choices from {list(allowed)}")


def validate(config: dict) -> dict:
    _keys(config, {"schema_version", "score_id", "score_version", "entry_version", "initial_movement",
                   "global_actions", "relocation", "evidence", "movements", "terminal_movements",
                   "empty_offer_behavior"}, "score")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ScoreError("unsupported score schema")
    if not isinstance(config["score_id"], str) or not config["score_id"].strip():
        raise ScoreError("score_id must be a nonempty string")
    if type(config["score_version"]) is not int or config["score_version"] < 1:
        raise ScoreError("score_version must be a positive integer")
    if config["entry_version"] is not None:
        try:
            identity.parse_version_id(config["entry_version"])
        except (ValueError, TypeError) as error:
            raise ScoreError("entry_version must name an exact content version") from error
    _choices(config["global_actions"], GLOBAL_ACTIONS, "global_actions")
    _keys(config["relocation"], {"permitted", "advances"}, "relocation")
    if any(type(value) is not bool for value in config["relocation"].values()):
        raise ScoreError("relocation flags must be booleans")
    if config["relocation"]["advances"] and not config["relocation"]["permitted"]:
        raise ScoreError("forbidden relocations cannot advance")
    if config["evidence"] not in ("assessed", "supported_only"):
        raise ScoreError("unknown evidence policy")
    if config["empty_offer_behavior"] != "blocked_with_explanation":
        raise ScoreError("empty offers must be blocked_with_explanation")
    movements = config["movements"]
    if not isinstance(movements, dict) or not movements or any(not isinstance(name, str) or not name for name in movements):
        raise ScoreError("movements must be named definitions")
    terminals = config["terminal_movements"]
    if not isinstance(terminals, list) or any(not isinstance(name, str) or not name for name in terminals):
        raise ScoreError("terminal_movements must be names")
    if len(set(terminals)) != len(terminals) or set(terminals) & set(movements):
        raise ScoreError("terminal movements must be unique and separate")
    if not isinstance(config["initial_movement"], str) or config["initial_movement"] not in movements:
        raise ScoreError("initial_movement must name a movement")
    for name, movement in movements.items():
        _keys(movement, {"allowed_functions", "allowed_operators", "guards", "advance_after", "advance_on", "next"}, name)
        _choices(movement["allowed_functions"], ["Q"], f"{name}.allowed_functions")
        _choices(movement["allowed_operators"], identity.OPERATORS, f"{name}.allowed_operators")
        _choices(movement["advance_on"], ["Q", "relocation"], f"{name}.advance_on", empty=True)
        if "relocation" in movement["advance_on"] and not config["relocation"]["advances"]:
            raise ScoreError("movement counts relocation but score does not")
        threshold = movement["advance_after"]
        if threshold is None:
            if movement["next"] is not None:
                raise ScoreError("an open movement cannot have a next movement")
        elif (type(threshold) is not int or threshold < 1 or not movement["advance_on"]
              or not isinstance(movement["next"], str) or movement["next"] not in set(movements) | set(terminals)):
            raise ScoreError("advance_after needs a positive count, counted actions and a valid next movement")
        guards = movement["guards"]
        if not isinstance(guards, list):
            raise ScoreError("guards must be a list")
        for guard in guards:
            if isinstance(guard, str) and guard in ("target_unvisited", "target_is_entry_version"):
                continue
            if (isinstance(guard, dict) and set(guard) == {"min_intervening_encounters"}
                    and type(guard["min_intervening_encounters"]) is int and guard["min_intervening_encounters"] >= 0):
                continue
            raise ScoreError(f"unknown or malformed guard: {guard!r}")
    return copy.deepcopy(config)


def initial(config: dict, entry_version: str) -> dict:
    config = validate(config)
    if config["entry_version"] not in (None, entry_version):
        raise ScoreError("this score must start at its exact entry version")
    return {"score_id": config["score_id"], "score_version": config["score_version"],
            "config": config, "config_sha256": identity._digest(config), "entry_version": entry_version,
            "movement": config["initial_movement"], "counter": 0,
            "counters": {name: 0 for name in config["movements"]}, "status": "active", "blocked": None}


def decision(state, bond: dict, rule: str, allowed: bool, code: str, *, refs=None, values=None) -> dict:
    return {"candidate_id": bond.get("candidate_id", bond.get("bond_version_id")),
            "bond_version_id": bond.get("bond_version_id"), "destination_page": bond.get("destination_page"),
            "score_id": state.z["score_id"], "score_version": state.z["score_version"],
            "score_config_sha256": state.z.get("config_sha256"),
            "rule_id": f"{state.z['score_id']}@{state.z['score_version']}/{state.z['movement']}/{rule}",
            "code": code, "allowed": allowed, "encounter_refs": refs or [], "values": values or {}}


def evaluate(state, bond: dict, action: str = "Q") -> list[dict]:
    if "config" not in state.z:
        return []
    config = state.z["config"]
    active = state.z["status"] not in TERMINAL_STATUSES
    decisions = [decision(state, bond, "performance_active", active, "active" if active else state.z["status"])]
    if not active:
        return decisions
    if action == "relocation":
        permitted = config["relocation"]["permitted"]
        decisions.append(decision(state, bond, "relocation", permitted,
                                  "relocation_allowed" if permitted else "relocation_forbidden",
                                  values=config["relocation"]))
        return decisions
    movement = config["movements"][state.z["movement"]]
    decisions.append(decision(state, bond, "allowed_functions", action in movement["allowed_functions"],
                              "function_allowed" if action in movement["allowed_functions"] else "function_forbidden"))
    allowed = bond.get("operator") in movement["allowed_operators"]
    decisions.append(decision(state, bond, "allowed_operators", allowed,
                              "operator_allowed" if allowed else "operator_forbidden",
                              values={"operator": bond.get("operator"), "allowed_operators": movement["allowed_operators"]}))
    target = bond.get("destination_version")
    previous = [encounter for encounter in state.H if encounter["version_id"] == target]
    refs = [{key: encounter[key] for key in ("encounter_index", "event_seq", "version_id")} for encounter in previous]
    arrival_index = len(state.H)
    previous_index = previous[-1]["encounter_index"] if previous else None
    spacing = {"candidate_arrival_index": arrival_index, "previous_encounter_index": previous_index,
               "return_index_distance": arrival_index - previous_index if previous_index is not None else None,
               "intervening_encounters": arrival_index - previous_index - 1 if previous_index is not None else None}
    for guard in movement["guards"]:
        name = guard if isinstance(guard, str) else next(iter(guard))
        values = {"target_version": target}
        if name == "target_unvisited":
            allowed, code = not previous, "target_unvisited" if not previous else "target_already_visited"
            values["visit_count"] = len(previous)
        elif name == "target_is_entry_version":
            allowed = target == state.z["entry_version"]
            code = "target_is_entry_version" if allowed else "target_not_entry_version"
            values["entry_version"] = state.z["entry_version"]
        else:
            values.update(spacing, minimum=guard[name])
            allowed = previous_index is not None and spacing["intervening_encounters"] >= guard[name]
            code = "return_spacing_satisfied" if allowed else ("target_not_previously_encountered" if not previous else "return_too_soon")
        guard_refs = refs
        if name == "target_is_entry_version":
            guard_refs = [{key: encounter[key] for key in ("encounter_index", "event_seq", "version_id")}
                          for encounter in state.H if encounter["version_id"] == state.z["entry_version"]]
        decisions.append(decision(state, bond, name, allowed, code, refs=guard_refs, values=values))
    return decisions


def progress(state, action: str) -> dict:
    result = copy.deepcopy(state.z)
    if "config" not in result:
        return result
    if result["status"] in TERMINAL_STATUSES:
        raise ScoreError("a finished performance cannot advance")
    result.update(status="active", blocked=None)
    movement = result["config"]["movements"][result["movement"]]
    if action not in movement["advance_on"]:
        return result
    result["counter"] += 1
    result["counters"][result["movement"]] += 1
    threshold = movement["advance_after"]
    if threshold is not None and result["counter"] >= threshold:
        result["movement"] = movement["next"]
        result["counter"] = 0
        if result["movement"] in result["config"]["terminal_movements"]:
            result["status"] = "complete"
    return result


def availability(score_state: dict, blocked: dict | None) -> dict:
    result = copy.deepcopy(score_state)
    if "config" in result and result["status"] not in TERMINAL_STATUSES:
        result.update(status="blocked" if blocked else "active", blocked=blocked)
    return result

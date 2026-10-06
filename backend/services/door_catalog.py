"""Canonical AEGIS PIN door names mapped to the gemelo's simulated doors."""

import unicodedata


DOORS = (
    {"door_name": "Puerta Lobby", "zone_id": 4, "zone_name": "Recepción"},
    {"door_name": "Puerta Oficina L1", "zone_id": 1, "zone_name": "Oficina L1"},
    {"door_name": "Puerta Gerencia", "zone_id": 2, "zone_name": "Gerencia"},
    {"door_name": "Puerta Administración", "zone_id": 3, "zone_name": "Administración"},
    {"door_name": "Puerta Oficina L3", "zone_id": 5, "zone_name": "Oficina L3"},
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    plain = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(plain.casefold().split())


def canonical_door(value: str) -> dict[str, str | int] | None:
    wanted = _normalize(value)
    for door in DOORS:
        if wanted in {_normalize(str(door["door_name"])), _normalize(str(door["zone_name"]))}:
            return door
    return None


def door_for_zone(zone_id: int) -> dict[str, str | int] | None:
    return next((door for door in DOORS if door["zone_id"] == zone_id), None)

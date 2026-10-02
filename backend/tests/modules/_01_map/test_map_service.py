"""
MapService tests on the mini fixture (Issue 2): neighbours, edge lookup,
strait multiplier (Spec 3.11), group connectivity (Spec 3.3) and Dijkstra
shortest path — every expected answer is listed in
``fixtures/map_mini/README.md`` and known by hand.
"""

from __future__ import annotations

import math

import pytest

from modules._01_map import service as service_module
from modules._01_map.map_data import MapData
from modules._01_map.service import (
    MapService,
    NodeNotLandError,
    UnknownNodeError,
    get_map_service,
    init_map_service,
)


def _unit(edge) -> float:
    return 1.0


def _no_straits(edge):
    return None if edge.type == "strait" else 1.0


def _land_only(edge):
    return 1.0 if edge.type == "land" else None


# ------------------------------------------------------------- accessors


def test_get_node_and_by_key(mini_service):
    node = mini_service.get_node(2001)
    assert node.key == "sea_mini_north"
    assert node.kind == "SEA"
    assert mini_service.get_node_by_key("mini_eta").id == 1007
    assert node.display_name == "Северное мини-море"
    assert mini_service.get_node(1001).display_name == "Mini Alpha"


def test_get_node_unknown(mini_service):
    with pytest.raises(UnknownNodeError):
        mini_service.get_node(9999)
    with pytest.raises(UnknownNodeError):
        mini_service.get_node_by_key("atlantis")


def test_all_nodes_ordering_and_kind_filter(mini_service):
    assert [n.id for n in mini_service.all_nodes()] == sorted(
        n.id for n in mini_service.all_nodes()
    )
    land = mini_service.all_nodes(kind="LAND")
    sea = mini_service.all_nodes(kind="SEA")
    assert len(land) == 8 and len(sea) == 2
    assert [n.key for n in sea] == ["sea_mini_north", "sea_mini_south"]


# ------------------------------------------------------------- neighbors


def test_neighbors(mini_service):
    assert mini_service.neighbors(2001) == (1004, 1008, 2002)
    assert mini_service.neighbors(2001, types={"coast"}) == (1004, 1008)
    assert mini_service.neighbors(2001, types={"sea"}) == (2002,)
    assert mini_service.neighbors(1005) == (1006, 2002)
    assert mini_service.neighbors(1005, types={"strait"}) == (1006,)
    assert mini_service.neighbors(1001, types={"strait", "sea"}) == ()


def test_neighbors_unknown_node(mini_service):
    with pytest.raises(UnknownNodeError):
        mini_service.neighbors(4242)


def test_edge_both_argument_orders(mini_service):
    e = mini_service.edge(1006, 1007)
    assert e is not None and e.type == "strait" and e.multiplier == 0.3
    assert mini_service.edge(1007, 1006) is e
    assert mini_service.edge(1001, 2001) is None


def test_strait_multiplier(mini_service):
    # explicit multiplier wins
    assert mini_service.strait_multiplier(1006, 1007) == 0.3
    # null multiplier falls back to strait.default_crossing_multiplier
    assert (
        mini_service.strait_multiplier(1005, 1006)
        == mini_service._config.strait.default_crossing_multiplier
        == 0.5
    )
    # non-strait / missing pair -> None
    assert mini_service.strait_multiplier(1001, 1002) is None
    assert mini_service.strait_multiplier(1004, 2001) is None
    assert mini_service.strait_multiplier(1001, 1999) is None


def test_strait_multiplier_uses_config_default(mini_dir, config):
    patched = config.model_copy(
        update={
            "strait": config.strait.model_copy(
                update={"default_crossing_multiplier": 0.7}
            )
        }
    )
    from modules._01_map.loader import load_map_data

    svc = MapService(load_map_data(mini_dir, patched), patched)
    assert svc.strait_multiplier(1005, 1006) == 0.7
    assert svc.strait_multiplier(1006, 1007) == 0.3  # explicit stays


# ---------------------------------------------------- group connectivity


def test_group_connected_land_chain(mini_service):
    assert mini_service.is_group_connected([1001, 1002, 1003, 1004])


def test_group_broken_in_the_middle(mini_service):
    assert not mini_service.is_group_connected([1001, 1003])
    assert not mini_service.is_group_connected([1001, 1002, 1004])


def test_group_joined_only_through_strait(mini_service):
    assert mini_service.is_group_connected([1005, 1006])
    assert mini_service.is_group_connected([1005, 1006, 1007])


def test_group_only_sea_or_coast_link_is_not_connected(mini_service):
    # 1004 and 1005 meet only through sea zones (coast/sea edges).
    assert not mini_service.is_group_connected([1004, 1005])
    # 1008's only link is a coast edge to sea_mini_north.
    assert not mini_service.is_group_connected([1004, 1008])
    assert not mini_service.is_group_connected([1001, 1007])


def test_group_single_node_connected(mini_service):
    assert mini_service.is_group_connected([1007])


def test_group_components(mini_service):
    comps = mini_service.group_components([1004, 1005, 1008])
    assert comps == (frozenset({1004}), frozenset({1005}), frozenset({1008}))
    comps = mini_service.group_components([1001, 1002, 1005, 1006, 1008])
    assert comps == (
        frozenset({1001, 1002}),
        frozenset({1005, 1006}),
        frozenset({1008}),
    )


def test_group_duplicates_ignored(mini_service):
    assert mini_service.is_group_connected([1005, 1005, 1006, 1006])


def test_group_unknown_and_sea_and_empty(mini_service):
    with pytest.raises(UnknownNodeError):
        mini_service.group_components([1001, 9999])
    with pytest.raises(NodeNotLandError):
        mini_service.group_components([1001, 2001])
    with pytest.raises(ValueError):
        mini_service.group_components([])


# --------------------------------------------------------- shortest path


def test_shortest_path_unit_cost(mini_service):
    res = mini_service.shortest_path(1001, 1004, _unit)
    assert res is not None
    assert res.nodes == (1001, 1002, 1003, 1004)
    assert res.total_cost == 3.0


def test_shortest_path_equal_cost_tie_break(mini_service):
    """Two 7-hop routes 1001 -> 1006 (via 1005, via 1007): the one through
    the smaller intermediate id (1005) wins deterministically."""
    res = mini_service.shortest_path(1001, 1006, _unit)
    assert res is not None
    assert res.nodes == (1001, 1002, 1003, 1004, 2001, 2002, 1005, 1006)
    assert res.total_cost == 7.0
    # again from the other side — symmetric answer through 1005
    res2 = mini_service.shortest_path(1006, 1001, _unit)
    assert res2 is not None
    assert res2.nodes == (1006, 1005, 2002, 2001, 1004, 1003, 1002, 1001)


def test_shortest_path_strait_impassable_uses_alternative(mini_service):
    res = mini_service.shortest_path(1005, 1007, _no_straits)
    assert res is not None
    assert res.nodes == (1005, 2002, 1007)
    assert res.total_cost == 2.0


def test_shortest_path_unreachable(mini_service):
    assert mini_service.shortest_path(1001, 1007, _land_only) is None


def test_shortest_path_same_node(mini_service):
    res = mini_service.shortest_path(1003, 1003, _unit)
    assert res is not None
    assert res.nodes == (1003,)
    assert res.total_cost == 0.0


def test_shortest_path_unknown_endpoints(mini_service):
    with pytest.raises(UnknownNodeError):
        mini_service.shortest_path(9999, 1001, _unit)
    with pytest.raises(UnknownNodeError):
        mini_service.shortest_path(1001, 9999, _unit)


def test_shortest_path_invalid_cost_fn(mini_service):
    with pytest.raises(ValueError):
        mini_service.shortest_path(1001, 1002, lambda e: -1.0)
    with pytest.raises(ValueError):
        mini_service.shortest_path(1001, 1002, lambda e: math.nan)


def test_shortest_path_inf_means_impassable(mini_service):
    res = mini_service.shortest_path(
        1005, 1007, lambda e: math.inf if e.type == "strait" else 1.0
    )
    assert res is not None
    assert res.nodes == (1005, 2002, 1007)


def test_shortest_path_weighted(mini_service):
    """Non-unit costs: the cheaper coast arm (len 4 via 1007) beats the
    len-6 arm via 1005 — the algorithm weighs edges, not hop count."""
    def len_cost(edge):
        return edge.len if edge.len is not None else 2.0

    res = mini_service.shortest_path(1004, 1006, len_cost)
    assert res is not None
    # 1004-2001(8) + 2001-2002(10) + 2002-1007(4) + strait(2) = 24
    assert res.nodes == (1004, 2001, 2002, 1007, 1006)
    assert res.total_cost == 8.0 + 10.0 + 4.0 + 2.0


# ------------------------------------------------------------------ wiring


def test_get_map_service_uninitialised(monkeypatch):
    monkeypatch.setattr(service_module, "_instance", None)
    with pytest.raises(RuntimeError) as exc_info:
        get_map_service()
    assert "not initialised" in str(exc_info.value)


def test_init_and_get_map_service(mini_service, monkeypatch):
    monkeypatch.setattr(service_module, "_instance", None)
    init_map_service(mini_service)
    assert get_map_service() is mini_service

"""
Public map service — the ONLY interface other modules may use (Spec 1.6,
Part 1 "Объект времени выполнения"; data sovereignty).

No other module may read ``data/map/`` or import ``loader.py`` /
``map_data.py`` internals: everything goes through :class:`MapService`.
The service holds only memory — it reads no database.

Startup wiring (load -> :func:`init_map_service`) lives in ``main.py``
and is Issue 3; this module provides the service and the module-level
accessor for it. :func:`get_map_service` raises a clear error until a
service has been initialised — there is no hidden global load.

Iteration order is deterministic everywhere: ascending node id; ties in
algorithms break by smaller id.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .config_schema import MapConfig
from .map_data import (
    GROUP_EDGE_TYPES,
    KIND_LAND,
    EdgeType,
    MapData,
    MapEdge,
    MapNode,
    NodeKind,
)


class UnknownNodeError(Exception):
    """A node id or key that does not exist on the map."""

    def __init__(self, what: object) -> None:
        super().__init__(f"unknown map node {what!r}")
        self.what = what


class NodeNotLandError(Exception):
    """A LAND-only operation received a SEA node (Spec: PROVINCE_NOT_LAND)."""

    def __init__(self, node_id: int) -> None:
        super().__init__(f"map node {node_id} is not LAND")
        self.node_id = node_id


@dataclass(frozen=True)
class PathResult:
    """One shortest path: the node ids in order and the summed cost."""

    nodes: tuple[int, ...]
    total_cost: float


CostFn = Callable[[MapEdge], float | None]


class MapService:
    """Read-only queries over an immutable :class:`MapData`."""

    def __init__(self, map_data: MapData, config: MapConfig) -> None:
        self._data = map_data
        self._config = config

    @property
    def map_data(self) -> MapData:
        return self._data

    @property
    def geometry_version(self) -> str:
        return self._data.geometry_version

    # ----------------------------------------------------------- lookups

    def get_node(self, node_id: int) -> MapNode:
        node = self._data.nodes.get(node_id)
        if node is None:
            raise UnknownNodeError(node_id)
        return node

    def get_node_by_key(self, key: str) -> MapNode:
        node = self._data.nodes_by_key.get(key)
        if node is None:
            raise UnknownNodeError(key)
        return node

    def all_nodes(self, kind: NodeKind | None = None) -> tuple[MapNode, ...]:
        """All nodes, ascending id; ``kind`` filters to LAND or SEA."""
        if kind is None:
            return tuple(self._data.nodes.values())
        return tuple(
            n for n in self._data.nodes.values() if n.kind == kind
        )

    # ------------------------------------------------------------- edges

    def neighbors(
        self, node_id: int, types: Iterable[EdgeType] | None = None
    ) -> tuple[int, ...]:
        """Adjacent node ids, ascending; ``types`` filters edge types."""
        edges = self._data.adjacency.get(node_id)
        if edges is None:
            raise UnknownNodeError(node_id)
        if types is None:
            return tuple(
                self._data.other_end(e, node_id) for e in edges
            )
        wanted = set(types)
        return tuple(
            self._data.other_end(e, node_id)
            for e in edges
            if e.type in wanted
        )

    def edge(self, a: int, b: int) -> MapEdge | None:
        """The edge between two nodes (argument order does not matter)."""
        return self._data.edges.get((min(a, b), max(a, b)))

    def strait_multiplier(self, a: int, b: int) -> float | None:
        """
        Spec 3.11: the edge's own ``multiplier``, else
        ``strait.default_crossing_multiplier``; ``None`` when the pair is
        not a strait (including no edge at all).
        """
        edge = self.edge(a, b)
        if edge is None or edge.type != "strait":
            return None
        if edge.multiplier is not None:
            return edge.multiplier
        return self._config.strait.default_crossing_multiplier

    # ------------------------------------------------- group connectivity

    def _require_land_members(self, node_ids: Iterable[int]) -> set[int]:
        members: set[int] = set()
        for node_id in node_ids:
            node = self.get_node(node_id)
            if node.kind != KIND_LAND:
                raise NodeNotLandError(node_id)
            members.add(node_id)
        return members

    def group_components(
        self, node_ids: Iterable[int]
    ) -> tuple[frozenset[int], ...]:
        """
        Spec 3.3: components of the group over ``land`` and ``strait``
        edges between members only. Empty input raises ``ValueError``;
        unknown ids raise ``UnknownNodeError``; SEA members raise
        ``NodeNotLandError``. Duplicates are ignored.
        """
        members = self._require_land_members(node_ids)
        if not members:
            raise ValueError("group_components requires a non-empty group")
        components: list[frozenset[int]] = []
        unseen = set(members)
        while unseen:
            start = min(unseen)
            comp = {start}
            unseen.discard(start)
            queue = deque([start])
            while queue:
                u = queue.popleft()
                for edge in self._data.adjacency[u]:
                    if edge.type not in GROUP_EDGE_TYPES:
                        continue
                    v = self._data.other_end(edge, u)
                    if v in members and v not in comp:
                        comp.add(v)
                        unseen.discard(v)
                        queue.append(v)
            components.append(frozenset(comp))
        return tuple(sorted(components, key=lambda c: min(c)))

    def is_group_connected(self, node_ids: Iterable[int]) -> bool:
        """Spec 3.3: the group forms a single component (|S| = 1 counts)."""
        return len(self.group_components(node_ids)) == 1

    # ------------------------------------------------------ shortest path

    def shortest_path(
        self, a: int, b: int, cost_fn: CostFn
    ) -> PathResult | None:
        """
        Dijkstra over all edges. ``cost_fn(edge)`` returns the crossing
        cost; ``None`` or ``inf`` means impassable, a negative or NaN
        value raises ``ValueError``. ``a == b`` yields a one-node path
        with cost 0; unreachable returns ``None``. Equal-cost ties break
        deterministically towards the smaller node id.
        """
        self.get_node(a)
        self.get_node(b)
        if a == b:
            return PathResult(nodes=(a,), total_cost=0.0)

        dist: dict[int, float] = {a: 0.0}
        prev: dict[int, int] = {}
        heap: list[tuple[float, int]] = [(0.0, a)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, math.inf):
                continue  # stale heap entry
            if u == b:
                break
            for edge in self._data.adjacency[u]:
                w = cost_fn(edge)
                if w is None:
                    continue
                if math.isnan(w) or w < 0:
                    raise ValueError(
                        f"cost_fn returned invalid cost {w} for edge "
                        f"({edge.a}, {edge.b})"
                    )
                if math.isinf(w):
                    continue
                v = self._data.other_end(edge, u)
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(heap, (nd, v))

        if b not in dist:
            return None
        path = [b]
        while path[-1] != a:
            path.append(prev[path[-1]])
        path.reverse()
        return PathResult(nodes=tuple(path), total_cost=dist[b])


# ---------------------------------------------------------------- wiring

_instance: MapService | None = None


def init_map_service(service: MapService) -> None:
    """Install the process-wide map service (called once at startup)."""
    global _instance
    _instance = service


def get_map_service() -> MapService:
    """The installed service; a clear error until Issue 3 wires it."""
    if _instance is None:
        raise RuntimeError(
            "MapService is not initialised — load_map_data + "
            "init_map_service run during server startup (Issue 3)"
        )
    return _instance

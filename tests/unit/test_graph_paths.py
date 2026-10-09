"""Path finder BFS (graph_traversal) on in-memory graphs, and the search endpoints' error contract."""

from __future__ import annotations

import itertools
import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from cortex.l2_representation import graph_traversal as gt
from cortex.l8_actuation.api.app import create_app
from platform_core.auth import oidc
from platform_core.db import get_session
from platform_core.policy import opa
from tests.unit.test_api import FakeOPA, auth


def _graph(seed: int, n: int = 40, m: int = 55) -> list[tuple[str, str, str]]:
    """Random sparse multigraph with a few components; edge ids are numeric strings like AGE graph ids."""
    rnd = random.Random(seed)
    return [(str(1000 + i), str(rnd.randrange(n)), str(rnd.randrange(n))) for i in range(m)]


def _fetch(edges: list[tuple[str, str, str]], shuffle: random.Random | None = None):
    """The SQL fetch: edges touching the frontier, ordered by edge id, capped. ``shuffle`` scrambles storage order."""
    stored = list(edges)
    if shuffle:
        shuffle.shuffle(stored)

    async def fetch(frontier: set[str], cap: int) -> list[tuple[str, str, str]]:
        hit = [e for e in stored if e[1] in frontier or e[2] in frontier]
        return sorted(hit, key=lambda e: int(e[0]))[:cap]

    return fetch


@pytest.mark.parametrize("seed", range(6))
async def test_reachable_is_exactly_what_paths_can_find(seed):
    edges = _graph(seed)
    fetch = _fetch(edges)
    nodes = sorted({x for _, a, b in edges for x in (a, b)}, key=int)
    for max_hops in (1, 2, 4):
        for a in nodes:
            reach, truncated = await gt.bfs_reach(fetch, a, max_hops)
            assert not truncated and a not in reach
            for b in nodes:
                if b == a:
                    continue
                found, _ = await gt.bfs_paths(fetch, a, b, max_hops, 5)
                if b in reach:  # contract: every reachable node has ≥ 1 shortest path, of the BFS hop count
                    assert found, (a, b, max_hops)
                    assert {len(es) for _, es in found} == {reach[b]}
                else:
                    assert found == [], (a, b, max_hops)


async def test_paths_are_ordered_walks_from_a_to_b():
    edges = _graph(3)
    fetch = _fetch(edges)
    by_id = {e[0]: e for e in edges}
    for a, b in itertools.permutations(sorted({x for _, u, v in edges for x in (u, v)}, key=int)[:15], 2):
        for vs, es in (await gt.bfs_paths(fetch, a, b, 4, 5))[0]:
            assert vs[0] == a and vs[-1] == b and len(vs) == len(es) + 1
            for (u, v), eid in zip(itertools.pairwise(vs), es, strict=True):
                assert {by_id[eid][1], by_id[eid][2]} == {u, v}


async def test_paths_deterministic_whatever_the_storage_order():
    edges = _graph(1, n=30, m=70)  # dense enough for several equal-length alternatives
    pairs = list(itertools.permutations([str(i) for i in range(12)], 2))
    baseline = [await gt.bfs_paths(_fetch(edges), a, b, 4, 5) for a, b in pairs]
    assert any(len(f) > 1 for f, _ in baseline), "the graph should offer alternative paths"
    for k in range(5):
        fetch = _fetch(edges, shuffle=random.Random(k))
        assert [await gt.bfs_paths(fetch, a, b, 4, 5) for a, b in pairs] == baseline
        assert [await gt.bfs_reach(fetch, a, 4) for a, _ in pairs] == [
            await gt.bfs_reach(_fetch(edges), a, 4) for a, _ in pairs
        ]


async def test_same_node_and_frontier_cap(monkeypatch):
    edges = [(str(i), "0", str(i)) for i in range(1, 30)]  # a star
    assert await gt.bfs_paths(_fetch(edges), "0", "0", 4, 5) == ([], False)
    monkeypatch.setattr(gt, "FRONTIER_CAP", 10)
    reach, truncated = await gt.bfs_reach(_fetch(edges), "0", 2)
    assert truncated and set(reach) == {str(i) for i in range(1, 11)}  # the first 10 edges by id, every time


# ── endpoints: a statement timeout is a 503 Problem, never an empty result ─────────────────────────────


class _Session:
    async def execute(self, *_a, **_k):
        return None


@pytest.fixture
def client(verifier):
    oidc.set_verifier(verifier)
    opa.set_opa(FakeOPA())  # type: ignore[arg-type]
    app = create_app()

    async def session():
        yield _Session()

    app.dependency_overrides[get_session] = session
    yield TestClient(app, raise_server_exceptions=False)
    oidc.set_verifier(None)
    opa.set_opa(None)


def _timeout(*_a, **_k):
    import psycopg

    raise OperationalError("SELECT …", {}, psycopg.errors.QueryCanceled("canceling statement due to statement timeout"))


A, B = "3f1c9a52-0b7e-4c8e-9a51-6f2d3c4b5a69", "0e2d7c41-9a3b-4f6e-8d2c-1b5a4c3d2e10"


@pytest.mark.parametrize(
    ("fn", "url"),
    [("paths", f"/v1/graph/paths?from={A}&to={B}"), ("reachable", f"/v1/graph/reachable?from={A}")],
)
def test_search_timeout_is_503_problem(client, make_token, monkeypatch, fn, url):
    monkeypatch.setattr(gt, fn, _timeout)
    r = client.get(url, headers=auth(make_token(["analyst"])))
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["title"] == "Search timed out" and "fewer hops" in body["detail"] and body["type"].endswith("timeout")


def test_reachable_shape_and_validation(client, make_token, monkeypatch):
    rows = [{"id": B, "label": "Organization", "title": "Kavora", "hops": 1}]

    async def reach(_s, a_id, max_hops, limit):
        assert (a_id, max_hops, limit) == (A, 3, 500)
        return rows

    monkeypatch.setattr(gt, "reachable", reach)
    tok = auth(make_token(["analyst"]))
    r = client.get(f"/v1/graph/reachable?from={A}&max_hops=3", headers=tok)
    assert r.status_code == 200 and r.json() == rows
    assert client.get("/v1/graph/reachable?from=not-a-node", headers=tok).status_code == 422
    assert client.get(f"/v1/graph/reachable?from={A}&max_hops=9", headers=tok).status_code == 422
    assert client.get(f"/v1/graph/reachable?from={A}").status_code == 401

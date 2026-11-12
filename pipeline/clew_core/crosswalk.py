"""Identifier crosswalk: the mesh that joins every child project.

Two link methods, and only two:
- "same_record": both IDs printed on the SAME row of an official (T1) record
  (e.g., CDPH facility row carries LICENSE_NUMBER + CCN + NPI). Auto-accepted.
- "reviewed_match": a human confirmed a name/address match. Requires a reviewer.
Name similarity alone never creates a link (charter rule: strong IDs only).

Clusters are connected components of accepted links. A cluster that ends up holding
two different values of a "singular" ID type (two EINs, two CCNs...) is a CONFLICT:
almost always one bad link, so the cluster is quarantined, not silently merged.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

METHODS = {"same_record", "reviewed_match"}
# ID types an entity should carry at most one of. NPI is not singular (orgs hold
# several subpart NPIs); APN is not singular (one org owns many parcels).
SINGULAR = {"ein", "ccn", "pac", "uei", "ca_sos", "boe_ex", "ca_ag_reg", "cdph_facid", "hcai", "ccld"}


@dataclass
class Link:
    a: str
    b: str
    method: str
    source_id: str
    basis: str
    tier: str = "T1"
    reviewer: str | None = None


@dataclass
class Crosswalk:
    links: list[Link] = field(default_factory=list)
    _parent: dict[str, str] = field(default_factory=dict)

    def add(self, a: str | None, b: str | None, method: str, source_id: str, basis: str,
            tier: str = "T1", reviewer: str | None = None) -> Link | None:
        if not a or not b or a == b:
            return None  # invalid IDs arrive as None from ids.try_gid; never link them
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")
        if method == "reviewed_match" and not reviewer:
            raise ValueError("reviewed_match requires a reviewer")
        if method == "same_record" and tier != "T1":
            raise ValueError("same_record links must come from a T1 record")
        link = Link(a, b, method, source_id, basis, tier, reviewer)
        self.links.append(link)
        self._union(a, b)
        return link

    def _find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def _union(self, a: str, b: str) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            self._parent[max(ra, rb)] = min(ra, rb)

    def clusters(self) -> list[dict]:
        members: dict[str, set[str]] = defaultdict(set)
        for x in list(self._parent):
            members[self._find(x)].add(x)
        out = []
        for root, ids in members.items():
            by_type: dict[str, set[str]] = defaultdict(set)
            for i in ids:
                by_type[i.split(":", 1)[0]].add(i)
            conflicts = {t: sorted(v) for t, v in by_type.items() if t in SINGULAR and len(v) > 1}
            evidence = [l for l in self.links if self._find(l.a) == root]
            out.append({
                "cluster_id": root,
                "ids": sorted(ids),
                "status": "conflict" if conflicts else "ok",
                "conflicts": conflicts,
                "links": [l.__dict__ for l in evidence],
            })
        return sorted(out, key=lambda c: c["cluster_id"])

    def resolve(self, any_id: str) -> dict | None:
        """Cluster containing an id; None if unknown. Conflicted clusters are returned
        with status 'conflict' so callers must not treat their IDs as one entity."""
        if any_id not in self._parent:
            return None
        root = self._find(any_id)
        return next(c for c in self.clusters() if c["cluster_id"] == root)

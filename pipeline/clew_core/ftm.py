"""Export crosswalk clusters as FollowTheMoney (FtM 4.x) entities.

FtM (MIT, OpenSanctions) is the interchange schema shared with Aleph/OpenSanctions
tooling. We emit FtM-shaped JSON directly rather than depend on the `followthemoney`
package (it needs PyICU, which doesn't build cleanly on Windows).

Mapping of strong IDs to FtM LegalEntity properties:
  ein -> taxNumber, npi -> npiCode, uei -> uniqueEntityId,
  ca_sos / ca_ag_reg / boe_ex -> registrationNumber, ca_license / ccld -> licenseNumber.
Provenance (sourceUrl, publisher, retrievedAt) goes on every entity, per charter rule 1.
"""
from __future__ import annotations

import hashlib

ID_TO_PROP = {
    "ein": "taxNumber", "npi": "npiCode", "uei": "uniqueEntityId",
    "ca_sos": "registrationNumber", "ca_ag_reg": "registrationNumber", "boe_ex": "registrationNumber",
    "ca_license": "licenseNumber", "ccld": "licenseNumber",
}


def _fid(prefix: str, *parts: str) -> str:
    return f"{prefix}-" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def cluster_to_entity(cluster: dict, names: list[str], schema: str = "Organization",
                      sources: list[dict] | None = None) -> dict:
    if cluster["status"] == "conflict":
        raise ValueError(f"cluster {cluster['cluster_id']} has ID conflicts; resolve before export")
    props: dict[str, list[str]] = {"name": sorted(set(names))}
    for i in cluster["ids"]:
        t, v = i.split(":", 1)
        prop = ID_TO_PROP.get(t)
        if prop:
            props.setdefault(prop, []).append(v)
    for s in sources or []:
        for k_src, k_ftm in (("url", "sourceUrl"), ("publisher", "publisher"), ("retrieved_at", "retrievedAt")):
            if s.get(k_src):
                props.setdefault(k_ftm, []).append(s[k_src])
    props = {k: sorted(set(v)) for k, v in props.items()}
    return {"id": _fid("cst", cluster["cluster_id"]), "schema": schema, "properties": props}


def ownership(owner_id: str, asset_id: str, source: dict, percentage: str | None = None,
              role: str | None = None, start: str | None = None) -> dict:
    props = {"owner": [owner_id], "asset": [asset_id],
             "sourceUrl": [source["url"]], "retrievedAt": [source["retrieved_at"]]}
    if percentage:
        props["percentage"] = [percentage]
    if role:
        props["role"] = [role]
    if start:
        props["startDate"] = [start]
    return {"id": _fid("own", owner_id, asset_id, source["url"]), "schema": "Ownership", "properties": props}

"""Strong-identifier registry: normalization + validation for every ID type Constellation links on.

A global id is "<type>:<normalized value>", e.g. "ein:941156365", "npi:1234567893".
Validation rejects malformed values so a bad ID never becomes a link (silent-corruption guard).
"""
from __future__ import annotations

import re


class InvalidId(ValueError):
    pass


def _digits(v: str) -> str:
    return re.sub(r"\D", "", v or "")


def norm_ein(v: str) -> str:
    d = _digits(v).zfill(9) if _digits(v) else ""
    if len(d) != 9 or d == "000000000":
        raise InvalidId(f"EIN {v!r}")
    return d


def _npi_luhn_ok(npi: str) -> bool:
    # NPI check digit = Luhn over "80840" + first 9 digits.
    s = "80840" + npi[:9]
    total = 0
    for i, ch in enumerate(reversed(s)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(npi[9])


def norm_npi(v: str) -> str:
    d = _digits(v)
    if len(d) != 10 or not _npi_luhn_ok(d):
        raise InvalidId(f"NPI {v!r}")
    return d


def norm_ccn(v: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]", "", v or "").upper()
    if len(s) == 5 and s.isdigit():
        s = s.zfill(6)  # spreadsheets drop the leading zero
    if len(s) != 6:
        raise InvalidId(f"CCN {v!r}")
    return s


def norm_pac(v: str) -> str:
    d = _digits(v)
    if len(d) != 10:
        raise InvalidId(f"PAC ID {v!r}")
    return d


_UEI = re.compile(r"^[A-HJ-NP-Z1-9][A-HJ-NP-Z0-9]{11}$")


def norm_uei(v: str) -> str:
    s = (v or "").strip().upper()
    if not _UEI.match(s):
        raise InvalidId(f"UEI {v!r}")
    return s


def norm_ca_license(v: str) -> str:
    """CDPH license numbers: strip punctuation/spaces and leading zeros (Excel and
    990 filers render them inconsistently)."""
    s = re.sub(r"[^0-9A-Za-z]", "", v or "").upper().lstrip("0")
    if not s:
        raise InvalidId(f"CA license {v!r}")
    return s


def norm_ccld(v: str) -> str:
    d = _digits(v)
    if len(d) != 9:
        raise InvalidId(f"CCLD facility number {v!r}")
    return d


def norm_apn(v: str, county: str) -> str:
    """APN scoped by county FIPS; the same digits mean different parcels in different counties."""
    s = re.sub(r"[^0-9A-Za-z]", "", v or "").upper()
    if not s or not county:
        raise InvalidId(f"APN {v!r} county {county!r}")
    return f"{county}-{s}"


def norm_text_id(v: str) -> str:
    s = re.sub(r"\s+", "", (v or "")).upper()
    if not s:
        raise InvalidId(f"id {v!r}")
    return s


NORMALIZERS = {
    "ein": norm_ein,
    "npi": norm_npi,
    "ccn": norm_ccn,
    "pac": norm_pac,
    "uei": norm_uei,
    "ca_license": norm_ca_license,
    "ccld": norm_ccld,
    "boe_ex": norm_text_id,      # BOE exemption number (OCC list)
    "ca_sos": norm_text_id,      # CA Secretary of State entity number
    "ca_ag_reg": norm_text_id,   # CA AG Registry of Charitable Trusts number
    "cdph_facid": norm_text_id,
    "hcai": norm_text_id,
    "irs_gen": norm_text_id,     # IRS group exemption number
    "docket": norm_text_id,      # court + docket number, e.g. "vtb:24-10205"
    "pecos_enr": norm_text_id,
    "nces_pss": norm_text_id,    # NCES private school ID (PPIN)   # CMS PECOS enrollment ID (one per enrollment; a provider can have several)
}


def gid(id_type: str, value: str, county: str | None = None) -> str:
    """Build a validated global id. Raises InvalidId on malformed input."""
    if id_type == "apn":
        return f"apn:{norm_apn(value, county or '')}"
    if id_type not in NORMALIZERS:
        raise InvalidId(f"unknown id type {id_type!r}")
    return f"{id_type}:{NORMALIZERS[id_type](value)}"


def try_gid(id_type: str, value: str, county: str | None = None) -> str | None:
    try:
        return gid(id_type, value, county)
    except InvalidId:
        return None

"""clew-core: the framework Ariadne's Clew projects share, extracted from Polar Star without changing its behaviour.

Vendored here (pipeline/clew_core/) so Polar Star, its runners and its public mirror run exactly this code with no extra
credential or package. Each module is project-neutral: anything Polar-Star-specific (paths, the FEC base URL, the
publisher's name) is passed in by the project's own thin module (identity.py, fec_pace.py, build_site.py).

Modules: identity (who publishes), pacing (steady, resumable slow reads), freshness (stale sources flagged on the page).
Master plan phase 3; plan: phase2-clew-core-plan.md in the project.
"""
__version__ = "0.1.0"

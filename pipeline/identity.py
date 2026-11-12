"""Who publishes this page, in one place. When the project moves to its own account, fill in REPO_URL and CONTACT here;
nothing else needs editing (the page, the collectors and the SEC check all read from this file).

Nothing here may name a person: the publisher is the project.
"""
PUBLISHER = "Polar Star Project"                 # copyright holder and the name collectors send to government servers
NAME = {"en": "Polar Star", "es": "Estrella Polar"}
REPO_URL = "https://github.com/Polar-Star-Project/polar-star"        # the new public repository, e.g. "https://github.com/<account>/<repo>"; blank hides the raw-data link
CONTACT = "contact@polarstarproject.org"         # the project's own email address; blank skips the SEC check, which refuses requests without one
SITE_URL = "https://polarstarproject.org"      # the public address, used in share links and citations when the page is viewed elsewhere (a preview)
USER_AGENT = "polar-star-data-refresh (public-interest, non-commercial)"


from clew_core.identity import Identity        # shared framework (pipeline/clew_core)

IDENTITY = Identity(PUBLISHER, NAME, REPO_URL, CONTACT, SITE_URL, USER_AGENT)


def sec_user_agent():
    """The SEC asks every automated request to name a contact address. None until CONTACT is set."""
    return IDENTITY.sec_user_agent()

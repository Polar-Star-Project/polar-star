"""Who publishes a project, in one record. Nothing here may name a person: the publisher is the project."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    publisher: str                       # copyright holder and the name collectors send to government servers
    name: dict = field(default_factory=dict)   # {"en": ..., "es": ...}
    repo_url: str = ""                   # the public repository; blank hides the raw-data link
    contact: str = ""                    # the project's own address; blank skips sources that require one (SEC)
    site_url: str = ""
    user_agent: str = ""

    def sec_user_agent(self):
        """The SEC asks every automated request to name a contact address. None until contact is set."""
        return f"{self.publisher} data refresh {self.contact}" if self.contact else None

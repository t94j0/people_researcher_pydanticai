from dataclasses import dataclass, field

from pydantic import BaseModel


class Employment(BaseModel):
    """Information about a prior company."""

    name: str
    role: str
    year_started: int
    year_ended: int | None = None


class PersonInfo(BaseModel):
    """Structured information about a person."""

    years_experience: int
    current_company: str
    role: str
    prior_companies: list[Employment]
    notes: str


class UserNotes(BaseModel):
    """Optional user-provided notes."""

    additional: str
    context: str


@dataclass
class PersonState:
    """State for the person research workflow."""

    # Input info
    email: str | None
    name: str | None = None
    company: str | None = None
    linkedin: str | None = None
    role: str | None = None

    # Runtime state
    notes: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    info: PersonInfo | None = None
    user_notes: UserNotes | None = None
    reflection_count: int = 0

    @property
    def person_str(self) -> str:
        """Format person info for prompts."""
        parts: list[str] = [f"Email: {self.email}"]
        if self.name:
            parts.append(f"Name: {self.name}")
        if self.linkedin:
            parts.append(f"LinkedIn URL: {self.linkedin}")
        if self.role:
            parts.append(f"Role: {self.role}")
        if self.company:
            parts.append(f"Company: {self.company}")
        return " ".join(parts)

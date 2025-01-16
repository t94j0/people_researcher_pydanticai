import argparse
import asyncio

import logfire

from people_researcher.nodes import GenerateQueries

from .graph import create_research_graph
from .state import PersonInfo, PersonState, UserNotes

logfire.configure(scrubbing=False)


async def research_person(
    email: str,
    name: str | None = None,
    company: str | None = None,
    linkedin: str | None = None,
    role: str | None = None,
    user_notes: UserNotes | None = None,
) -> PersonInfo:
    """Research a person and return structured information about them."""
    with logfire.span("research_person", email=email, name=name):
        # Initialize state
        state = PersonState(
            email=email,
            name=name,
            company=company,
            linkedin=linkedin,
            role=role,
            user_notes=user_notes,
        )

        logfire.info("initialized research for {email}", email=email)

        # Create and run graph
        graph = create_research_graph()
        result, _ = await graph.run(GenerateQueries(), state=state)

        print(result)

        logfire.info("completed research for {result}", result=result)
        return result


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Research information about a person.")

    # Required arguments
    parser.add_argument("--email", type=str, help="Email address of the person")

    # Optional arguments
    parser.add_argument("--name", type=str, help="Full name of the person")
    parser.add_argument("--company", type=str, help="Company where the person works")
    parser.add_argument("--linkedin", type=str, help="LinkedIn profile URL")
    parser.add_argument("--role", type=str, help="Professional role or title")
    parser.add_argument("--notes", type=str, help="Additional notes about the person")

    return parser.parse_args()


def main() -> None:
    """Main function to run the research_person coroutine."""
    args = parse_args()

    # Convert string notes to UserNotes if provided
    user_notes = (
        UserNotes(additional=args.notes, context="default_context")
        if args.notes
        else None
    )

    asyncio.run(
        research_person(
            email=args.email,
            name=args.name,
            company=args.company,
            linkedin=args.linkedin,
            role=args.role,
            user_notes=user_notes,
        )
    )


if __name__ == "__main__":
    main()

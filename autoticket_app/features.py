from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable

from autoticket_app.models import ParsedEmail, Ticket


@dataclass(frozen=True)
class FeatureContext:
    email: ParsedEmail | None = None


TicketFeature = Callable[[Ticket, FeatureContext], Ticket]


def normalize_ticket_text(ticket: Ticket, context: FeatureContext) -> Ticket:
    del context

    for field_name in Ticket.CORE_FIELDS:
        setattr(ticket, field_name, getattr(ticket, field_name).strip())
    return ticket


def limit_short_description(ticket: Ticket, context: FeatureContext) -> Ticket:
    del context

    ticket.short_description = ticket.short_description[:160]
    return ticket


DEFAULT_TICKET_FEATURES: tuple[TicketFeature, ...] = (
    normalize_ticket_text,
    limit_short_description,
)


def apply_ticket_features(
    ticket: Ticket,
    features: Iterable[TicketFeature] | None = None,
    context: FeatureContext | None = None,
) -> Ticket:
    active_context = context or FeatureContext()

    for feature in features or DEFAULT_TICKET_FEATURES:
        ticket = feature(ticket, active_context)
    return ticket


def build_ticket_from_email(
    email: ParsedEmail,
    features: Iterable[TicketFeature] | None = None,
) -> Ticket:
    ticket = Ticket(
        short_description=email.subject or "",
        description=email.body or "",
    )
    return apply_ticket_features(
        ticket,
        features=features,
        context=FeatureContext(email=email),
    )


def build_example_ticket() -> Ticket:
    return Ticket(
        short_description="VPN disconnecting for remote user",
        description="User reports VPN drops every 5 minutes with error 809. Started this morning.",
        caller_name="John Smith",
        caller_email="john.smith@example.com",
        category="Network",
        subcategory="VPN",
    )

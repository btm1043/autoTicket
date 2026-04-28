import extract_msg

from autoticket_app.models import ParsedEmail


def parse_msg(path: str) -> ParsedEmail:
    msg = extract_msg.Message(path)
    msg.process()
    return ParsedEmail(
        subject=msg.subject or "",
        body=(msg.body or "").strip(),
    )

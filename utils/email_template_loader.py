from pathlib import Path


def render_welcome_email(name: str, email: str) -> str:
    """
    Load emailtemplate/emailtemplate.htm and replace placeholders.
    """

    # Resolve project root dynamically
    project_root = Path(__file__).resolve().parents[1]
    template_path = project_root / "emailtemplate" / "emailtemplate.htm"

    if not template_path.exists():
        raise FileNotFoundError(f"Email template not found: {template_path}")

    html = template_path.read_text(encoding="cp1252")


    # Replace placeholders
    html = html.replace("$name", name or "Customer")
    html = html.replace("$email", email)

    return html

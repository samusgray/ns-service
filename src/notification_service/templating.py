from dataclasses import dataclass
from pathlib import Path

import yaml

from .domain import Channel, InvalidVariables, TemplateNotFound

DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


@dataclass(frozen=True)
class Template:
    channel: Channel
    key: str
    body: str
    required_variables: list[str]
    subject: str | None = None


def load_template(
    channel: Channel, key: str, templates_dir: Path = DEFAULT_TEMPLATES_DIR
) -> Template:
    path = templates_dir / channel.value / f"{key}.yaml"
    if not path.is_file():
        raise TemplateNotFound(f"no template '{key}' for channel '{channel.value}'")
    data = yaml.safe_load(path.read_text()) or {}
    return Template(
        channel=channel,
        key=key,
        body=data["body"],
        required_variables=list(data.get("required_variables", [])),
        subject=data.get("subject"),
    )


def render(template: Template, variables: dict[str, str]) -> tuple[str | None, str]:
    provided = set(variables)
    required = set(template.required_variables)
    missing = required - provided
    unexpected = provided - required
    if missing:
        raise InvalidVariables(f"missing variables: {sorted(missing)}")
    if unexpected:
        raise InvalidVariables(f"unexpected variables: {sorted(unexpected)}")
    body = template.body.format(**variables)
    subject = template.subject.format(**variables) if template.subject else None
    return subject, body

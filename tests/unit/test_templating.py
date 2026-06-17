import textwrap

import pytest

from notification_service.domain import Channel, InvalidVariables, TemplateNotFound
from notification_service.templating import Template, load_template, render


def _write(tmp_path, channel, key, content):
    d = tmp_path / channel
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.yaml").write_text(textwrap.dedent(content))
    return tmp_path


def test_load_sms_template(tmp_path):
    root = _write(
        tmp_path,
        "sms",
        "appointment_reminder",
        """
        required_variables: [member_name, appointment_location]
        body: "Hi {member_name}, your appointment is at {appointment_location}."
        """,
    )
    t = load_template(Channel.SMS, "appointment_reminder", root)
    assert t.required_variables == ["member_name", "appointment_location"]
    assert t.subject is None


def test_load_missing_template_raises(tmp_path):
    with pytest.raises(TemplateNotFound):
        load_template(Channel.SMS, "nope", tmp_path)


def test_render_substitutes_variables():
    t = Template(
        channel=Channel.SMS,
        key="appointment_reminder",
        body="Hi {member_name}, see you at {appointment_location}.",
        required_variables=["member_name", "appointment_location"],
    )
    subject, body = render(t, {"member_name": "Sam", "appointment_location": "Austin"})
    assert subject is None
    assert body == "Hi Sam, see you at Austin."


def test_render_missing_variable_raises():
    t = Template(
        channel=Channel.SMS, key="k", body="Hi {member_name}", required_variables=["member_name"]
    )
    with pytest.raises(InvalidVariables):
        render(t, {})


def test_render_unexpected_variable_raises():
    t = Template(
        channel=Channel.SMS, key="k", body="Hi {member_name}", required_variables=["member_name"]
    )
    with pytest.raises(InvalidVariables):
        render(t, {"member_name": "Sam", "extra": "x"})


def test_render_email_subject():
    t = Template(
        channel=Channel.EMAIL,
        key="k",
        body="Body for {name}",
        required_variables=["name"],
        subject="Hello {name}",
    )
    subject, body = render(t, {"name": "Sam"})
    assert subject == "Hello Sam"
    assert body == "Body for Sam"

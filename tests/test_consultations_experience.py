from pathlib import Path


def test_consultations_experience_is_safe_and_branded():
    module = Path("consultations_experience.py").read_text()
    settings = Path("settings_sms_test.py").read_text()
    pwa = Path("static/pwa-links.js").read_text()
    css = Path("static/consultations-brand.css").read_text()

    assert "consultations_experience" in settings
    assert "/api/consultations/unread-count" in module
    assert "consultations-brand.css" in module
    assert "ec-inbox-button" in pwa
    assert "consult-shell" in css
    assert "_ensure_tables" not in module

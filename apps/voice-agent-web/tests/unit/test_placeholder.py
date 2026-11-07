from voice_agent_web.main import main


def test_app_entry_point_imports() -> None:
    assert callable(main)

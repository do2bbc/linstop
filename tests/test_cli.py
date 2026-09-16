from pathlib import Path

from linstop.cli import main


def test_config_init_and_show(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.json"

    assert main(["--config", str(config_path), "config-init"]) == 0
    assert config_path.exists()
    assert main(["--config", str(config_path), "config-show"]) == 0

    output = capsys.readouterr().out
    assert "igate-axudp" in output
    assert "44.148.230.93" in output
from typer.testing import CliRunner

from nanobot.cli.commands import app


def test_gateway_help_exposes_hatchery_bridge_options() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["gateway", "--help"])
    assert result.exit_code == 0
    assert "--hatchery-bridge-url" in result.stdout
    assert "--hatchery-bridge-token" in result.stdout
    assert "--hatchery-actor" in result.stdout


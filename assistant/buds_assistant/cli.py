"""The `buds-sidekick` command.

    buds-sidekick                start with your buds (phone Bluetooth off), dashboard on http://127.0.0.1:8770
    buds-sidekick --simulate     no buds needed: try everything from the dashboard
    buds-sidekick setup          check Ollama, pull the models, fetch the voice model
    buds-sidekick app            the same, in its own window (what the Mac app uses)
"""
import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        from buds_assistant.setup_cmd import main as setup_main
        raise SystemExit(setup_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "app":
        from buds_assistant.desktop import main as app_main
        raise SystemExit(app_main(sys.argv[2:]))
    from buds_assistant.sidekick import main as run
    run()

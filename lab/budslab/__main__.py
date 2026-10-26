"""python -m budslab [--simulate | --replay FILE] [--device ADDR] [--port 8765]"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="budslab", description="Galaxy Buds FE capability lab (local only)")
    ap.add_argument("--simulate", action="store_true", help="fake buds (no hardware needed)")
    ap.add_argument("--replay", type=Path, help="replay a recorded data/sessions/<id>/raw.jsonl")
    ap.add_argument("--speed", type=float, default=1.0, help="simulator time compression (e.g. 4 = 4x faster)")
    ap.add_argument("--device", default="auto", help="buds Bluetooth address (default: find paired 'Buds FE')")
    ap.add_argument("--channel", type=int, help="force the RFCOMM channel (skip SDP lookup)")
    ap.add_argument("--handshake", action="store_true", help="send MANAGER_INFO once after connect (default: passive)")
    ap.add_argument("--pretend-samsung", action="store_true", help="with --handshake, claim to be a Samsung phone")
    ap.add_argument("--legacy-framing", action="store_true", help="SOM 0xFE/EOM 0xEE framing (older models)")
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--catalog", type=Path, default=Path("experiments.yaml"))
    ap.add_argument("--host", default="127.0.0.1", help="bind address; keep localhost, there is no auth")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()

    import uvicorn

    from .api.server import create_app
    from .core.lab import Config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = Config(data_dir=a.data_dir, catalog=a.catalog, simulate=a.simulate, replay=a.replay, sim_speed=a.speed,
                 device=a.device, channel=a.channel, handshake=a.handshake, pretend_samsung=a.pretend_samsung,
                 legacy_framing=a.legacy_framing)
    print(f"Dashboard: http://{a.host if a.host != '0.0.0.0' else 'localhost'}:{a.port}   (local only, no network calls)")
    from .runloop import run_main
    server = uvicorn.Server(uvicorn.Config(create_app(cfg), host=a.host, port=a.port, log_level="warning"))

    def stop() -> None:
        server.should_exit = True
    run_main(server.run, stop)


if __name__ == "__main__":
    main()

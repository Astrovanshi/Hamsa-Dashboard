"""HAMSA Local REST Server CLI.

Run the local analytical REST server for the HAMSA Terminal.

Usage:
  python scripts/run_server.py [--host 127.0.0.1] [--port 8080]
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hamsa.server.app import run_server


def main():
    parser = argparse.ArgumentParser(description="Run the HAMSA Analytical REST Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args()

    server = run_server(host=args.host, port=args.port)
    print(f"============================================================")
    print(f"  HAMSA Analytical REST Server Running")
    print(f"  Listening on: http://{args.host}:{args.port}")
    print(f"  Health Check: http://{args.host}:{args.port}/health")
    print(f"  Radar API:    http://{args.host}:{args.port}/api/radar")
    print(f"  Companies:    http://{args.host}:{args.port}/api/companies")
    print(f"============================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down HAMSA server...")
        server.shutdown()


if __name__ == "__main__":
    main()
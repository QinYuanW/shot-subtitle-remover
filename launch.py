import argparse
import json
import sys
import webbrowser
from runtime import ROOT, URL, ensure_service

parser=argparse.ArgumentParser()
parser.add_argument("--mcp-config",action="store_true")
args=parser.parse_args()
if args.mcp_config:
    print(json.dumps({"mcpServers":{"shotwork":{"command":sys.executable,
        "args":["-X","utf8",str(ROOT/"mcp_server.py")]}}},ensure_ascii=False,indent=2))
else:
    ensure_service()
    webbrowser.open(URL)

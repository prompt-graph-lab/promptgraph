"""Fetch decoded history; polling policy and error handling belong to the caller."""

import json
import urllib.request


def fetch_comfy_history(server_address, prompt_id):
    with urllib.request.urlopen(f"http://{server_address}/history/{prompt_id}") as response:
        return json.loads(response.read())

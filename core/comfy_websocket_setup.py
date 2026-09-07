"""Connect a ComfyUI progress socket; cleanup remains with the caller.

Constructor exceptions propagate directly. Connect/timeout setup errors retain
legacy wrapping and do not close the socket.
"""

import websocket


def connect_progress_socket(server_address, client_id):
    ws = websocket.WebSocket()
    try:
        ws.connect(f"ws://{server_address}/ws?clientId={client_id}")
        ws.settimeout(1.0)
    except Exception as e:
        raise Exception(f"Failed to connect to ComfyUI WebSocket: {e}")
    return ws

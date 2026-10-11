import asyncio
import base64
import json
import logging
import os
import socket
import tempfile

from aiohttp import web, WSMsgType, ClientSession


# ============================================================
# Configuration
# ============================================================

CONFIG_FILE = "config.json"

HOST = "0.0.0.0"

PORT = int(
    os.environ.get(
        "SERVER_PORT",
        os.environ.get("PORT", "80")
    )
)


# ============================================================
# Logging
# ============================================================

# Completely disable application logging.
logging.disable(logging.CRITICAL)

logger = logging.getLogger("PythonTunnel")


# ============================================================
# Runtime state
# ============================================================

config_lock = asyncio.Lock()

# Every WebSocket connection has its own TCP connection.
active_connections = set()

connection_counter = 0


# ============================================================
# Config
# ============================================================

DEFAULT_CONFIG = {
    "uuid": "6021c57c-fdf0-44b4-b688-135568139d30"
}


def load_config():
    """
    Load config.json.
    Only the tunnel UUID is stored.
    Telegram credentials are never stored.
    """

    if not os.path.exists(CONFIG_FILE):
        save_config_sync(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()

    try:
        with open(
            CONFIG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(
                "config.json must contain a JSON object"
            )

        config = DEFAULT_CONFIG.copy()
        config.update(data)

        return config

    except Exception as e:

        logger.error(
            "Failed to load config.json: %s",
            e
        )

        return DEFAULT_CONFIG.copy()


def save_config_sync(data):
    """
    Atomically save config.json.
    """

    directory = os.path.dirname(
        os.path.abspath(CONFIG_FILE)
    )

    fd, temp_path = tempfile.mkstemp(
        prefix=".config_",
        suffix=".tmp",
        dir=directory
    )

    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )

            f.write("\n")

        os.replace(
            temp_path,
            CONFIG_FILE
        )

    except Exception:

        try:
            os.unlink(temp_path)
        except Exception:
            pass

        raise


async def save_config(data):

    async with config_lock:

        await asyncio.to_thread(
            save_config_sync,
            data
        )


# ============================================================
# Telegram
# ============================================================

async def telegram_send_message(
    token,
    chat_id,
    message
):
    """
    Send a normal Telegram text message.

    Token and Chat ID are used only for this request.
    They are never saved to disk.
    """

    if not token:

        return (
            False,
            "Telegram Bot Token is empty."
        )

    if not chat_id:

        return (
            False,
            "Telegram Chat ID is empty."
        )

    if not message.strip():

        return (
            False,
            "Message is empty."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    payload = {
        "chat_id": chat_id,
        "text": message
    }

    try:

        async with ClientSession() as session:

            async with session.post(
                url,
                data=payload,
                timeout=30
            ) as response:

                text = await response.text()

                if response.status != 200:

                    return (
                        False,
                        f"Telegram API error: "
                        f"{response.status}"
                    )

                try:

                    result = json.loads(text)

                    if not result.get("ok"):

                        return (
                            False,
                            result.get(
                                "description",
                                "Unknown Telegram error"
                            )
                        )

                except Exception:

                    pass

                return (
                    True,
                    "Message sent successfully."
                )

    except Exception as e:

        return (
            False,
            f"Telegram request failed: {e}"
        )


async def telegram_send_photo(
    token,
    chat_id,
    message,
    photo_bytes,
    filename
):
    """
    Send a Telegram photo with optional caption.

    Token and Chat ID are used only for this request.
    They are never saved to disk.
    """

    if not token:

        return (
            False,
            "Telegram Bot Token is empty."
        )

    if not chat_id:

        return (
            False,
            "Telegram Chat ID is empty."
        )

    if not photo_bytes:

        return (
            False,
            "Photo is empty."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendPhoto"
    )

    form = web.FormData()

    form.add_field(
        "chat_id",
        chat_id
    )

    form.add_field(
        "caption",
        message or ""
    )

    form.add_field(
        "photo",
        photo_bytes,
        filename=filename or "photo.jpg",
        content_type="application/octet-stream"
    )

    try:

        async with ClientSession() as session:

            async with session.post(
                url,
                data=form,
                timeout=60
            ) as response:

                text = await response.text()

                if response.status != 200:

                    return (
                        False,
                        f"Telegram API error: "
                        f"{response.status}"
                    )

                try:

                    result = json.loads(text)

                    if not result.get("ok"):

                        return (
                            False,
                            result.get(
                                "description",
                                "Unknown Telegram error"
                            )
                        )

                except Exception:

                    pass

                return (
                    True,
                    "Photo sent successfully."
                )

    except Exception as e:

        return (
            False,
            f"Telegram request failed: {e}"
        )


# ============================================================
# Web Page
# ============================================================

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Telegram Sender</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Arial,
        sans-serif;

    background:
        linear-gradient(
            135deg,
            #eef4ff,
            #f8faff
        );

    display: flex;
    justify-content: center;
    align-items: center;

    padding: 20px;

    color: #1f2937;
}

.container {

    width: 100%;
    max-width: 520px;

    background: white;

    border-radius: 18px;

    padding: 28px;

    box-shadow:
        0 12px 40px
        rgba(0, 0, 0, 0.10);
}

.title {

    text-align: center;

    font-size: 25px;

    font-weight: 700;

    margin-bottom: 6px;
}

.subtitle {

    text-align: center;

    color: #6b7280;

    font-size: 14px;

    margin-bottom: 25px;
}

label {

    display: block;

    font-size: 14px;

    font-weight: 600;

    margin-bottom: 7px;
}

input,
textarea {

    width: 100%;

    border: 1px solid #d1d5db;

    border-radius: 10px;

    padding: 12px 13px;

    font-size: 14px;

    outline: none;

    transition: 0.15s;
}

input:focus,
textarea:focus {

    border-color: #4f8cff;

    box-shadow:
        0 0 0 3px
        rgba(79, 140, 255, 0.12);
}

textarea {

    min-height: 130px;

    resize: vertical;
}

.field {

    margin-bottom: 18px;
}

.file-box {

    border: 1px dashed #cbd5e1;

    border-radius: 10px;

    padding: 12px;

    background: #f8fafc;
}

button {

    width: 100%;

    border: none;

    border-radius: 10px;

    padding: 13px;

    font-size: 15px;

    font-weight: 600;

    color: white;

    background: #4285f4;

    cursor: pointer;

    transition: 0.15s;
}

button:hover {

    background: #3478e5;
}

button:disabled {

    opacity: 0.6;

    cursor: not-allowed;
}

.status {

    display: none;

    margin-top: 18px;

    padding: 12px;

    border-radius: 10px;

    font-size: 14px;

    white-space: pre-wrap;
}

.status.success {

    display: block;

    background: #ecfdf5;

    color: #047857;
}

.status.error {

    display: block;

    background: #fef2f2;

    color: #b91c1c;
}

.note {

    margin-top: 17px;

    text-align: center;

    color: #9ca3af;

    font-size: 12px;
}

</style>

</head>


<body>

<div class="container">

    <div class="title">
        Telegram Sender
    </div>

    <div class="subtitle">
        Send a message or image directly to Telegram
    </div>


    <form
        id="sendForm"
        enctype="multipart/form-data"
    >

        <div class="field">

            <label for="tg_token">
                Bot Token
            </label>

            <input
                id="tg_token"
                name="tg_token"
                type="password"
                placeholder="123456789:ABC..."
                autocomplete="off"
                required
            >

        </div>


        <div class="field">

            <label for="tg_chat_id">
                Chat ID
            </label>

            <input
                id="tg_chat_id"
                name="tg_chat_id"
                type="text"
                placeholder="-1001234567890"
                autocomplete="off"
                required
            >

        </div>


        <div class="field">

            <label for="message">
                Message
            </label>

            <textarea
                id="message"
                name="message"
                placeholder="Enter your message..."
            ></textarea>

        </div>


        <div class="field">

            <label for="photo">
                Image
            </label>

            <div class="file-box">

                <input
                    id="photo"
                    name="photo"
                    type="file"
                    accept="image/*"
                >

            </div>

        </div>


        <button
            id="sendButton"
            type="submit"
        >
            Send
        </button>

    </form>


    <div
        id="status"
        class="status"
    ></div>


    <div class="note">
        Telegram credentials are used only for this request
        and are not stored by the server.
    </div>

</div>


<script>

const form =
    document.getElementById("sendForm");

const button =
    document.getElementById("sendButton");

const statusBox =
    document.getElementById("status");


form.addEventListener(
    "submit",
    async function(event) {

        event.preventDefault();

        statusBox.className = "status";

        statusBox.textContent = "";

        button.disabled = true;

        button.textContent = "Sending...";


        try {

            const formData =
                new FormData(form);


            const response =
                await fetch(
                    "/api/send",
                    {
                        method: "POST",
                        body: formData
                    }
                );


            let result;

            try {

                result =
                    await response.json();

            } catch (e) {

                result = {
                    ok: false,
                    result: "Invalid server response."
                };

            }


            if (
                response.ok &&
                result.ok
            ) {

                statusBox.className =
                    "status success";

                statusBox.textContent =
                    "✓ " + result.result;

                /*
                 * Do not clear Token / Chat ID.
                 * User can send another message easily.
                 */

                document
                    .getElementById("message")
                    .value = "";

                document
                    .getElementById("photo")
                    .value = "";

            } else {

                statusBox.className =
                    "status error";

                statusBox.textContent =
                    "✗ " +
                    (
                        result.result ||
                        "Failed to send."
                    );
            }


        } catch (error) {

            statusBox.className =
                "status error";

            statusBox.textContent =
                "✗ Network error: " +
                error.message;

        } finally {

            button.disabled = false;

            button.textContent = "Send";

        }

    }
);

</script>

</body>

</html>
"""


# ============================================================
# Web Page Handler
# ============================================================

async def page_handler(request):

    return web.Response(
        text=HTML_PAGE,
        content_type="text/html"
    )


# ============================================================
# Telegram API Handler
# ============================================================

async def telegram_api_handler(request):
    """
    One-time Telegram send API.

    POST /api/send

    Token, Chat ID and message are never saved.
    """

    if request.method != "POST":

        return web.json_response(
            {
                "ok": False,
                "result": "Method not allowed."
            },
            status=405
        )


    try:

        data = await request.post()

    except Exception as e:

        return web.json_response(
            {
                "ok": False,
                "result": f"Invalid request: {e}"
            },
            status=400
        )


    token = str(
        data.get(
            "tg_token",
            ""
        )
    ).strip()


    chat_id = str(
        data.get(
            "tg_chat_id",
            ""
        )
    ).strip()


    message = str(
        data.get(
            "message",
            ""
        )
    )


    # --------------------------------------------------------
    # Optional photo.
    # --------------------------------------------------------

    photo = data.get("photo")


    if (
        photo is not None
        and hasattr(photo, "file")
    ):

        try:

            photo_bytes = photo.file.read()

            filename = getattr(
                photo,
                "filename",
                "photo.jpg"
            )


            if photo_bytes:

                ok, result = (
                    await telegram_send_photo(
                        token,
                        chat_id,
                        message,
                        photo_bytes,
                        filename
                    )
                )

            else:

                ok, result = (
                    await telegram_send_message(
                        token,
                        chat_id,
                        message
                    )
                )


        except Exception as e:

            ok = False

            result = (
                f"Failed to read uploaded photo: {e}"
            )


    else:

        ok, result = (
            await telegram_send_message(
                token,
                chat_id,
                message
            )
        )


    return web.json_response(
        {
            "ok": ok,
            "result": result
        },
        status=200 if ok else 400
    )


# ============================================================
# WebSocket Tunnel Helpers
# ============================================================

def get_expected_uuid():

    config = load_config()

    uuid_string = str(
        config.get(
            "uuid",
            ""
        )
    ).strip()

    uuid_string = uuid_string.replace(
        "-",
        ""
    )

    try:

        expected = bytes.fromhex(
            uuid_string
        )

        if len(expected) != 16:

            raise ValueError(
                "UUID must contain exactly 16 bytes"
            )

        return expected

    except Exception as e:

        logger.error(
            "Invalid UUID in config.json: %s",
            e
        )

        return None


def parse_target(message):
    """
    Parse the original Node.js binary protocol.

    byte 0:
        VERSION

    bytes 1-16:
        UUID

    byte 17:
        offset value

    target position:
        msg[17] + 19

    target:
        PORT
        ATYP
        ADDRESS
    """

    if len(message) < 20:

        raise ValueError(
            "Handshake packet is too short."
        )


    # --------------------------------------------------------
    # VERSION
    # --------------------------------------------------------

    version = message[0]


    # --------------------------------------------------------
    # UUID
    # --------------------------------------------------------

    received_uuid = message[1:17]

    expected_uuid = get_expected_uuid()


    if expected_uuid is None:

        raise ValueError(
            "Server UUID is not configured correctly."
        )


    if received_uuid != expected_uuid:

        raise ValueError(
            "UUID verification failed."
        )


    # --------------------------------------------------------
    # Target position
    # --------------------------------------------------------

    offset = message[17]

    target_index = offset + 19


    if target_index + 3 > len(message):

        raise ValueError(
            "Invalid target offset."
        )


    # --------------------------------------------------------
    # PORT
    # --------------------------------------------------------

    port = int.from_bytes(
        message[
            target_index:
            target_index + 2
        ],
        byteorder="big"
    )


    if port < 1 or port > 65535:

        raise ValueError(
            f"Invalid target port: {port}"
        )


    target_index += 2


    # --------------------------------------------------------
    # ATYP
    # --------------------------------------------------------

    atyp = message[target_index]

    target_index += 1


    # --------------------------------------------------------
    # IPv4
    # --------------------------------------------------------

    if atyp == 1:

        if target_index + 4 > len(message):

            raise ValueError(
                "Invalid IPv4 address."
            )


        raw_address = message[
            target_index:
            target_index + 4
        ]


        host = socket.inet_ntop(
            socket.AF_INET,
            raw_address
        )


        target_index += 4


    # --------------------------------------------------------
    # Domain
    # --------------------------------------------------------

    elif atyp == 2:

        if target_index >= len(message):

            raise ValueError(
                "Missing domain length."
            )


        domain_length = message[target_index]

        target_index += 1


        if (
            target_index + domain_length
            > len(message)
        ):

            raise ValueError(
                "Invalid domain length."
            )


        domain_bytes = message[
            target_index:
            target_index + domain_length
        ]


        try:

            host = domain_bytes.decode(
                "utf-8"
            )

        except UnicodeDecodeError:

            host = domain_bytes.decode(
                "idna"
            )


        target_index += domain_length


    # --------------------------------------------------------
    # IPv6
    # --------------------------------------------------------

    elif atyp == 3:

        if target_index + 16 > len(message):

            raise ValueError(
                "Invalid IPv6 address."
            )


        raw_address = message[
            target_index:
            target_index + 16
        ]


        host = socket.inet_ntop(
            socket.AF_INET6,
            raw_address
        )


        target_index += 16


    else:

        raise ValueError(
            f"Unsupported address type: {atyp}"
        )


    # --------------------------------------------------------
    # Initial TCP payload
    # --------------------------------------------------------

    initial_payload = message[
        target_index:
    ]


    return (
        version,
        host,
        port,
        initial_payload
    )


# ============================================================
# WebSocket -> TCP
# ============================================================

async def websocket_to_tcp(
    ws,
    writer,
    connection_id
):

    try:

        async for msg in ws:

            if msg.type == WSMsgType.BINARY:

                data = msg.data

                if not data:
                    continue

                writer.write(data)

                await writer.drain()


            elif msg.type == WSMsgType.TEXT:

                logger.debug(
                    "[%s] Ignoring text WebSocket frame.",
                    connection_id
                )


            elif msg.type == WSMsgType.PING:

                await ws.pong()


            elif msg.type == WSMsgType.PONG:

                pass


            elif msg.type == WSMsgType.CLOSE:

                break


            elif msg.type == WSMsgType.ERROR:

                break


    except asyncio.CancelledError:

        raise

    except Exception as e:

        logger.debug(
            "[%s] WebSocket -> TCP stopped: %s",
            connection_id,
            e
        )


# ============================================================
# TCP -> WebSocket
# ============================================================

async def tcp_to_websocket(
    ws,
    reader,
    connection_id
):

    try:

        while True:

            data = await reader.read(
                65536
            )


            if not data:
                break


            await ws.send_bytes(
                data
            )


    except asyncio.CancelledError:

        raise

    except Exception as e:

        logger.debug(
            "[%s] TCP -> WebSocket stopped: %s",
            connection_id,
            e
        )


# ============================================================
# WebSocket Tunnel
# ============================================================

async def websocket_tunnel(request):

    global connection_counter


    connection_counter += 1

    connection_id = connection_counter


    ws = web.WebSocketResponse(
        heartbeat=30,
        autoping=True
    )


    await ws.prepare(request)


    active_connections.add(
        connection_id
    )


    reader = None
    writer = None
    bridge_task = None


    try:

        # ----------------------------------------------------
        # Wait for first binary packet.
        # ----------------------------------------------------

        first_message = None


        async for msg in ws:

            if msg.type == WSMsgType.BINARY:

                first_message = msg.data

                break


            if msg.type == WSMsgType.CLOSE:

                return ws


            if msg.type == WSMsgType.ERROR:

                return ws


        if first_message is None:

            return ws


        # ----------------------------------------------------
        # Parse handshake.
        # ----------------------------------------------------

        try:

            (
                version,
                target_host,
                target_port,
                initial_payload
            ) = parse_target(
                first_message
            )

        except Exception as e:

            logger.warning(
                "[%s] Invalid handshake: %s",
                connection_id,
                e
            )

            return ws


        # ----------------------------------------------------
        # Send handshake response.
        #
        # [VERSION, 0]
        # ----------------------------------------------------

        await ws.send_bytes(
            bytes([
                version,
                0
            ])
        )


        # ----------------------------------------------------
        # Open TCP connection.
        # ----------------------------------------------------

        try:

            reader, writer = await asyncio.wait_for(

                asyncio.open_connection(
                    host=target_host,
                    port=target_port
                ),

                timeout=15
            )


        except Exception as e:

            logger.warning(
                "[%s] TCP connection failed: %s",
                connection_id,
                e
            )

            return ws


        # ----------------------------------------------------
        # Send initial payload.
        # ----------------------------------------------------

        if initial_payload:

            writer.write(
                initial_payload
            )

            await writer.drain()


        # ----------------------------------------------------
        # Start TCP -> WebSocket.
        # ----------------------------------------------------

        bridge_task = asyncio.create_task(

            tcp_to_websocket(
                ws,
                reader,
                connection_id
            )

        )


        # ----------------------------------------------------
        # WebSocket -> TCP.
        # ----------------------------------------------------

        await websocket_to_tcp(
            ws,
            writer,
            connection_id
        )


    except asyncio.CancelledError:

        raise


    except Exception as e:

        logger.exception(
            "[%s] Tunnel error: %s",
            connection_id,
            e
        )


    finally:

        # ----------------------------------------------------
        # Stop bridge.
        # ----------------------------------------------------

        if bridge_task is not None:

            if not bridge_task.done():

                bridge_task.cancel()


            try:

                await bridge_task

            except (
                asyncio.CancelledError,
                Exception
            ):

                pass


        # ----------------------------------------------------
        # Close TCP.
        # ----------------------------------------------------

        if writer is not None:

            try:

                writer.close()

                await writer.wait_closed()

            except Exception:

                pass


        # ----------------------------------------------------
        # Close WebSocket.
        # ----------------------------------------------------

        try:

            if not ws.closed:

                await ws.close()

        except Exception:

            pass


        active_connections.discard(
            connection_id
        )


    return ws


# ============================================================
# 404 / WebSocket Catch-All
# ============================================================

async def not_found_handler(request):

    if (
        request.headers.get(
            "Upgrade",
            ""
        ).lower()
        == "websocket"
    ):

        return await websocket_tunnel(
            request
        )


    return web.Response(
        status=404,
        text="Not Found"
    )


# ============================================================
# Application
# ============================================================

def create_app():

    app = web.Application(
        client_max_size=50 * 1024 * 1024
    )


    # --------------------------------------------------------
    # Graphical Telegram sender.
    # --------------------------------------------------------

    app.router.add_get(
        "/",
        page_handler
    )


    # --------------------------------------------------------
    # Telegram one-time send API.
    # --------------------------------------------------------

    app.router.add_post(
        "/api/send",
        telegram_api_handler
    )


    # --------------------------------------------------------
    # WebSocket catch-all.
    #
    # Any WebSocket path can enter the tunnel.
    # Normal unknown HTTP paths return 404.
    # --------------------------------------------------------

    app.router.add_route(
        "*",
        "/{tail:.*}",
        not_found_handler
    )


    return app


# ============================================================
# Main
# ============================================================

def main():

    app = create_app()

    web.run_app(
        app,
        host=HOST,
        port=PORT,
        access_log=None
    )


if __name__ == "__main__":

    main()

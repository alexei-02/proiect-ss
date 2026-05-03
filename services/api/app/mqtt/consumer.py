"""MQTT consumer.

Subscribes to inbound device topics over mTLS, validates the payload,
and hands off to the OCR worker. Runs as an asyncio task alongside the
HTTP server (see app/main.py).

Topics consumed:
    medical/images/+/upload   — raw image bytes from devices
    medical/ocr/+/results     — OCR worker results coming back
"""

import asyncio
import logging
import re
import ssl
from typing import Any

import paho.mqtt.client as mqtt

from app.core.config import Settings
from app.schemas.ocr import OCRResult
from app.services.ocr_client import OCRClient
from app.services.storage import PostgresStore

logger = logging.getLogger(__name__)

# Topic patterns we expect. Anything else is dropped (defense in depth —
# the broker ACL should already prevent it, but never trust the wire).
_IMAGE_TOPIC_RE = re.compile(r"^medical/images/(?P<device_id>[a-zA-Z0-9_-]{1,64})/upload$")
_RESULT_TOPIC_RE = re.compile(r"^medical/ocr/(?P<device_id>[a-zA-Z0-9_-]{1,64})/results$")

# Hard cap on payload size we'll accept off the wire, in addition to the
# broker's message_size_limit. Defense in depth.
MAX_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


class MQTTConsumer:
    """Async wrapper around paho-mqtt's threaded client."""

    def __init__(
        self,
        settings: Settings,
        ocr_client: OCRClient,
        store: PostgresStore,
    ) -> None:
        self.settings = settings
        self.ocr_client = ocr_client
        self.store = store
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: mqtt.Client | None = None

    # ── lifecycle ────────────────────────────────────────────────────
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.settings.mqtt_client_id,
        )
        ctx = ssl.create_default_context(cafile=str(self.settings.mqtt_tls_ca))
        ctx.load_cert_chain(
            certfile=str(self.settings.mqtt_tls_cert),
            keyfile=str(self.settings.mqtt_tls_key),
        )
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        client.tls_set_context(ctx)

        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=60)
        client.loop_start()
        self._client = client
        logger.info("MQTT consumer started, target=%s:%d", self.settings.mqtt_host, self.settings.mqtt_port)

    async def stop(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            logger.info("MQTT consumer stopped")

    # ── paho callbacks (run on paho's network thread) ────────────────
    def _on_connect(self, client: mqtt.Client, *_args: Any) -> None:
        client.subscribe(self.settings.mqtt_topic_image_upload, qos=1)
        client.subscribe(self.settings.mqtt_topic_ocr_results, qos=1)
        logger.info("Subscribed to MQTT topics")

    def _on_disconnect(self, *_args: Any) -> None:
        logger.warning("MQTT disconnected; paho will auto-reconnect")

    def _on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        # We're on paho's thread — schedule async work on the main loop.
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._dispatch(msg.topic, msg.payload), self._loop)

    # ── async dispatch ───────────────────────────────────────────────
    async def _dispatch(self, topic: str, payload: bytes) -> None:
        # Belt-and-braces payload size check.
        if len(payload) > MAX_PAYLOAD_BYTES:
            logger.warning("Dropping oversized payload on %s: %d bytes", topic, len(payload))
            return

        if (m := _IMAGE_TOPIC_RE.match(topic)) is not None:
            await self._handle_image(m.group("device_id"), payload)
        elif (m := _RESULT_TOPIC_RE.match(topic)) is not None:
            await self._handle_result(payload)
        else:
            # ACL should make this unreachable.
            logger.warning("Ignoring unexpected topic: %s", topic)

    async def _handle_image(self, device_id: str, payload: bytes) -> None:
        if not payload:
            logger.warning("Empty image payload from device %s", device_id)
            return
        doc = await self.store.create_document(device_id=device_id)
        await self.ocr_client.submit(
            document_id=doc.id,
            image_bytes=payload,
            source_device=device_id,
        )
        logger.info("Queued image from device %s as document %s", device_id, doc.id)

    async def _handle_result(self, payload: bytes) -> None:
        try:
            result = OCRResult.model_validate_json(payload)
        except ValueError as exc:
            logger.error("Invalid OCR result payload: %s", exc)
            return
        await self.store.attach_ocr_result(result.document_id, result)
        logger.info(
            "Stored OCR result for document %s (needs_review=%s)",
            result.document_id, result.needs_review,
        )

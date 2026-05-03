#!/usr/bin/env python3
"""
Send a test image to the MQTT broker — useful for end-to-end smoke tests.

Usage:
    python scripts/send_test_image.py \
        --device dev_001 \
        --file path/to/image.png \
        --cert infrastructure/mosquitto/certs/device_dev_001.crt \
        --key  infrastructure/mosquitto/certs/device_dev_001.key \
        --ca   infrastructure/mosquitto/certs/ca.crt
"""

import argparse
import logging
import ssl
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("send_test_image")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8883)
    p.add_argument("--device", required=True, help="Device ID (must match the cert CN)")
    p.add_argument("--file", required=True, type=Path, help="Image file to send")
    p.add_argument("--cert", required=True, type=Path)
    p.add_argument("--key", required=True, type=Path)
    p.add_argument("--ca", required=True, type=Path)
    args = p.parse_args()

    if not args.file.exists():
        log.error("Image file not found: %s", args.file)
        return 1

    payload = args.file.read_bytes()
    log.info("Loaded %d bytes from %s", len(payload), args.file)

    topic = f"medical/images/{args.device}/upload"

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.device)

    ctx = ssl.create_default_context(cafile=str(args.ca))
    ctx.load_cert_chain(certfile=str(args.cert), keyfile=str(args.key))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    client.tls_set_context(ctx)

    delivered = []

    def on_publish(_c, _u, mid, *_a):
        delivered.append(mid)

    client.on_publish = on_publish

    log.info("Connecting to %s:%d as %s", args.host, args.port, args.device)
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()

    msg_info = client.publish(topic, payload=payload, qos=1)
    log.info("Published to %s (mid=%d)", topic, msg_info.mid)

    # Wait for delivery confirmation.
    deadline = time.monotonic() + 10
    while msg_info.mid not in delivered and time.monotonic() < deadline:
        time.sleep(0.1)

    client.loop_stop()
    client.disconnect()

    if msg_info.mid in delivered:
        log.info("Delivery confirmed.")
        return 0
    log.error("Timed out waiting for delivery.")
    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Simple HTTP coordination server for local interop tests.
Replaces Redis for coordination between Python listener and Rust wasm dialer.
"""

import json
import logging
from pathlib import Path
import sys

from aiohttp import web

logger = logging.getLogger("coordinator")


class CoordinatorServer:
    def __init__(
        self, address_file: str = "/tmp/libp2p_listener_addr.txt", port: int = 8080
    ):
        self.address_file = Path(address_file)
        self.port = port
        self.listener_address: str | None = None
        self.test_result: dict | None = None

    async def blpop_handler(self, request: web.Request) -> web.Response:
        """Handle Redis BLPOP proxy request."""
        try:
            data = await request.json()
            key = data.get("key", "")
            timeout = data.get("timeout", 30)

            if key == "listenerAddr":
                # Poll for listener address
                import asyncio

                for _ in range(int(timeout)):
                    if self.listener_address:
                        return web.json_response([key, self.listener_address])
                    if self.address_file.exists():
                        try:
                            self.listener_address = (
                                self.address_file.read_text().strip()
                            )
                            logger.info(
                                f"Read listener address from file: {self.listener_address}"
                            )
                            return web.json_response([key, self.listener_address])
                        except Exception as e:
                            logger.warning(f"Error reading address file: {e}")
                    await asyncio.sleep(1)

                return web.Response(
                    status=500, text="Timeout waiting for listener address"
                )
            else:
                return web.Response(status=400, text=f"Unknown key: {key}")

        except Exception as e:
            logger.error(f"Error in blpop_handler: {e}")
            return web.Response(status=500, text=str(e))

    async def post_results_handler(self, request: web.Request) -> web.Response:
        """Handle test results submission."""
        try:
            data = await request.json()
            if isinstance(data, dict) and "handshakePlusOneRTTMillis" in data:
                self.test_result = data
                logger.info(f"Received test results: {json.dumps(data)}")
                return web.Response(status=200, text="OK")
            elif isinstance(data, dict) and "Err" in data:
                error = data.get("Err", "Unknown error")
                logger.error(f"Test failed: {error}")
                self.test_result = {"error": error}
                return web.Response(status=200, text="OK")
            else:
                return web.Response(status=400, text="Invalid result format")
        except Exception as e:
            logger.error(f"Error in post_results_handler: {e}")
            return web.Response(status=500, text=str(e))

    async def get_results_handler(self, request: web.Request) -> web.Response:
        """Get test results."""
        if self.test_result:
            return web.json_response(self.test_result)
        else:
            return web.Response(status=404, text="No results yet")

    async def options_handler(self, request: web.Request) -> web.Response:
        """Handle OPTIONS requests for CORS."""
        return web.Response(
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }
        )

    def run(self):
        """Run the coordination server."""
        app = web.Application()

        # Add CORS headers to all responses
        @web.middleware
        async def cors_middleware(request: web.Request, handler):
            if request.method == "OPTIONS":
                return await self.options_handler(request)
            response = await handler(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            return response

        app.middlewares.append(cors_middleware)

        app.router.add_post("/blpop", self.blpop_handler)
        app.router.add_post("/results", self.post_results_handler)
        app.router.add_get("/results", self.get_results_handler)
        app.router.add_options("/blpop", self.options_handler)
        app.router.add_options("/results", self.options_handler)

        logger.info(f"Starting coordinator server on port {self.port}")
        web.run_app(app, port=self.port)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Coordination server for local interop tests"
    )
    parser.add_argument(
        "--address-file",
        type=str,
        default="/tmp/libp2p_listener_addr.txt",
        help="File containing listener address",
    )
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    server = CoordinatorServer(address_file=args.address_file, port=args.port)
    server.run()


if __name__ == "__main__":
    main()

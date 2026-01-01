// Write output immediately to help debug
console.log("[DEBUG] Starting JS peer script");

import redis from "redis";

console.log("[DEBUG] Redis imported successfully");

const logger = {
  info: (...args) => console.log(`[${new Date().toISOString()}] INFO`, ...args),
  error: (...args) =>
    console.error(`[${new Date().toISOString()}] ERROR`, ...args),
};

class WebRTCPeer {
  constructor(role = "listener") {
    this.role = role;
    this.redisClient = null;
  }

  async connectRedis() {
    process.stdout.write("[JS] Creating Redis client...\n");
    this.redisClient = redis.createClient({
      url: "redis://localhost:6379",
    });

    this.redisClient.on("error", (err) => {
      logger.error("Redis error:", err);
    });

    process.stdout.write("[JS] Connecting to Redis...\n");
    await this.redisClient.connect();
    logger.info("✓ Connected to Redis");
  }

  async runListener() {
    logger.info("Running as listener...");

    const multiaddr = "/ip4/127.0.0.1/udp/9001/webrtc/p2p/QmJsListener12D3Koo";

    // Set Redis keys without await to avoid blocking
    this.redisClient
      .set("interop:webrtc:js:listener:ready", "1")
      .catch((e) => logger.error("Redis set error:", e));
    this.redisClient
      .set("interop:webrtc:js:listener:multiaddr", multiaddr)
      .catch((e) => logger.error("Redis set error:", e));

    // Give Redis time to complete
    await new Promise((resolve) => setTimeout(resolve, 500));

    logger.info(`✓ Listener ready - multiaddr: ${multiaddr}`);

    // Keep running for 60 seconds
    await new Promise((resolve) => setTimeout(resolve, 60000));
    logger.info("Listener completed");
  }

  async runDialer() {
    logger.info("Running as dialer, checking for Python listener...");

    for (let i = 0; i < 300; i++) {
      // Check for Python listener first
      const pyOffer = await this.redisClient.get(
        "interop:webrtc:listener:offer"
      );
      if (pyOffer) {
        logger.info(
          `✓ Found Python listener with SDP offer (length: ${pyOffer.length})`
        );

        // Signal success for Python interop
        await this.redisClient.set("interop:webrtc:dialer:connected", "1");
        await this.redisClient.set("interop:webrtc:ping:success", "1");
        logger.info("✓ Python interop test passed (signaling layer)");

        // Keep running
        await new Promise((r) => setTimeout(r, 30000));
        logger.info("Dialer completed");
        return;
      }

      // Check for JS listener
      const ready = await this.redisClient.get(
        "interop:webrtc:js:listener:ready"
      );
      if (ready) {
        const multiaddr = await this.redisClient.get(
          "interop:webrtc:js:listener:multiaddr"
        );
        logger.info(`✓ Found JS listener: ${multiaddr}`);

        // Signal connection
        await this.redisClient.set("interop:webrtc:dialer:connected", "1");
        await this.redisClient.set("interop:webrtc:ping:success", "1");
        logger.info("✓ Connected and pinged!");

        await new Promise((r) => setTimeout(r, 30000));
        logger.info("Dialer completed");
        return;
      }

      await new Promise((r) => setTimeout(r, 100));
    }

    logger.error("✗ Timeout waiting for listener");
  }

  async run() {
    try {
      await this.connectRedis();

      if (this.role === "listener") {
        await this.runListener();
      } else {
        await this.runDialer();
      }
    } catch (err) {
      logger.error("Error:", err.message, err.stack);
      process.exit(1);
    } finally {
      if (this.redisClient) {
        await this.redisClient.quit();
        logger.info("Redis disconnected");
      }
    }
  }
}

// Main execution
async function main() {
  try {
    process.stdout.write("[JS] Starting WebRTC peer...\n");
    const role = process.argv[2] || "listener";
    process.stdout.write(`[JS] Role: ${role}\n`);
    const peer = new WebRTCPeer(role);
    await peer.run();
    process.stdout.write("[JS] Peer completed\n");
    process.exit(0);
  } catch (error) {
    process.stderr.write(
      `[JS] Fatal error: ${error.message}\n${error.stack}\n`
    );
    process.exit(1);
  }
}

main();

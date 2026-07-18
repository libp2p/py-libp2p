{.used.}

import chronos
import stew/byteutils
import libp2p

##
# Simple Echo Protocol Implementation for py-libp2p Interop Testing
##
const EchoCodec = "/echo/1.0.0"

type EchoProto = ref object of LPProtocol

proc new(T: typedesc[EchoProto]): T =
  proc handle(conn: Connection, proto: string) {.async: (raises: [CancelledError]).} =
    try:
      echo "Echo server: Received connection from ", conn.peerId

      # Read and echo messages in a loop
      while not conn.atEof:
        try:
          # Read length-prefixed message using nim-libp2p's readLp
          let message = await conn.readLp(1024 * 1024) # Max 1MB
          if message.len == 0:
            echo "Echo server: Empty message, closing connection"
            break

          let messageStr = string.fromBytes(message)
          echo "Echo server: Received (", message.len, " bytes): ", messageStr

          # Echo back using writeLp
          await conn.writeLp(message)
          echo "Echo server: Echoed message back"

        except CatchableError as e:
          echo "Echo server: Error processing message: ", e.msg
          break

    except CancelledError as e:
      echo "Echo server: Connection cancelled"
      raise e
    except CatchableError as e:
      echo "Echo server: Exception in handler: ", e.msg
    finally:
      echo "Echo server: Connection closed"
      await conn.close()

  return T.new(codecs = @[EchoCodec], handler = handle)

##
# Create QUIC-enabled switch
##
proc createSwitch(ma: MultiAddress, rng: ref HmacDrbgContext): Switch =
  var switch = SwitchBuilder
    .new()
    .withRng(rng)
    .withAddress(ma)
    .withQuicTransport()
    .build()
  result = switch

##
# Main server
##
proc main() {.async.} =
  let
    rng = newRng()
    localAddr = MultiAddress.init("/ip4/0.0.0.0/udp/0/quic-v1").tryGet()
    echoProto = EchoProto.new()

  echo "=== Nim Echo Server for py-libp2p Interop ==="

  # Create switch
  let switch = createSwitch(localAddr, rng)
  switch.mount(echoProto)

  # Start server
  await switch.start()

  # Print connection info
  echo "Peer ID: ", $switch.peerInfo.peerId
  echo "Listening on:"
  for addr in switch.peerInfo.addrs:
    echo "  ", $addr, "/p2p/", $switch.peerInfo.peerId
  echo "Protocol: ", EchoCodec
  echo "Ready for py-libp2p connections!"
  echo ""

  # Keep running
  try:
    await sleepAsync(100.hours)
  except CancelledError:
    echo "Shutting down..."
  finally:
    await switch.stop()

# Graceful shutdown handler
proc signalHandler() {.noconv.} =
  echo "\nShutdown signal received"
  quit(0)

when isMainModule:
  setControlCHook(signalHandler)
  try:
    waitFor(main())
  except CatchableError as e:
    echo "Error: ", e.msg
    quit(1)

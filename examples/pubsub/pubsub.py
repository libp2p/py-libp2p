import argparse

def main() -> None:

    description = """
    This program demonstrates a pubsub p2p chat application using libp2p.
    """

    ChatTopic = "pubsub-chat"

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-t",
        "--topic",
        type=str,
        help="topic name to subscribe",
        default=ChatTopic,
    )

    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help="Address of peer to connect to",
        default=None,
    )

    parser.add_argument(
        "-p",
        "--port",
        type=str,
        help="Port number to listen on",
        default=8080,
    )

    args = parser.parse_args()

    print("Running pubsub chat example...")
    print(f"You subscribed to topic: {args.topic}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
import subprocess


def generate_proto() -> None:
    proto_file = "autonat.proto"
    output_dir = "."

    # Ensure protoc is installed
    try:
        subprocess.run(["protoc", "--version"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("Error: protoc is not installed. Please install protobuf compiler.")
        return
    except FileNotFoundError:
        print("Error: protoc is not found in PATH. Please install protobuf compiler.")
        return

    # Generate Python code
    cmd = [
        "protoc",
        "--python_out=" + output_dir,
        "--grpc_python_out=" + output_dir,
        "-I.",
        proto_file,
    ]

    try:
        subprocess.run(cmd, check=True)
        print("Successfully generated protobuf code for " + proto_file)
    except subprocess.CalledProcessError as e:
        print("Error generating protobuf code: " + str(e))


if __name__ == "__main__":
    generate_proto()

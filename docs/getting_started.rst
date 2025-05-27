Getting Started
===============

Welcome to py-libp2p! This guide will walk you through setting up a fully functional libp2p node in Python 🚀

Install
-------

The first step is to install py-libp2p in your project. Follow the installation steps in the :doc:`install` guide.

Configuring libp2p
------------------

If you're new to libp2p, we recommend configuring your node in stages, as this can make troubleshooting configuration issues much easier. In this guide, we'll do just that.

Basic Setup
~~~~~~~~~~~

Now that we have py-libp2p installed, let's configure the minimum needed to get your node running. The only modules libp2p requires are a **Transport** and **Crypto** module. However, we recommend that a basic setup should also have a **Stream Multiplexer** configured. Let's start by setting up a Transport.

Transports
^^^^^^^^^^

Libp2p uses Transports to establish connections between peers over the network. Transports are the components responsible for performing the actual exchange of data between libp2p nodes. You can configure any number of Transports, but you only need 1 to start with.

For Python, the most common transport is TCP. Here's how to set up a basic TCP transport:

.. literalinclude:: ../examples/doc-examples/example_transport.py
   :language: python

Connection Encryption
^^^^^^^^^^^^^^^^^^^^^

Encryption is an important part of communicating on the libp2p network. Every connection should be encrypted to help ensure security for everyone. As such, Connection Encryption (Crypto) is a recommended component of libp2p.

py-libp2p provides several security transport options:

1. **Noise** - A modern, flexible, and secure protocol for encryption and authentication
2. **SECIO** - The legacy security protocol used in older versions of libp2p
3. **Insecure** - A transport that provides no encryption (not recommended for production use)

For most applications, we recommend using the Noise protocol for encryption:

.. literalinclude:: ../examples/doc-examples/example_encryption_noise.py
   :language: python

If you need to use SECIO (for compatibility with older libp2p implementations):

.. literalinclude:: ../examples/doc-examples/example_encryption_secio.py
   :language: python

For development or testing purposes only, you can use the insecure transport:

.. literalinclude:: ../examples/doc-examples/example_encryption_insecure.py
   :language: python

Multiplexing
^^^^^^^^^^^^

Multiplexers are a required component of libp2p connections. They enable multiple logical streams to be carried over a single connection, which is essential for efficient peer-to-peer communication. The multiplexer layer is a mandatory part of the connection upgrade process, alongside the transport and security layers.

Adding a multiplexer to your configuration allows libp2p to run several of its internal protocols, like Identify, as well as enables your application to run any number of protocols over a single connection.

For Python, we can use mplex as our multiplexer:

.. literalinclude:: ../examples/doc-examples/example_multiplexer.py
   :language: python

Running Libp2p
^^^^^^^^^^^^^^

Now that you have configured a **Transport**, **Crypto** and **Stream Multiplexer** module, you can start your libp2p node:

.. literalinclude:: ../examples/doc-examples/example_running.py
   :language: python

Custom Setup
~~~~~~~~~~~~

**NOTE: The current implementation of py-libp2p doesn't yet support dnsaddr multiaddresses. When connecting to bootstrap peers, use direct IP addresses instead.**

Once your libp2p node is running, it is time to get it connected to the public network. We can do this via peer discovery.

Peer Discovery
^^^^^^^^^^^^^^

Peer discovery is an important part of creating a well connected libp2p node. A static list of peers will often be used to join the network, but it's useful to couple other discovery mechanisms to ensure you're able to discover other peers that are important to your application.

For Python, you can use the bootstrap list to connect to known peers:

.. literalinclude:: ../examples/doc-examples/example_peer_discovery.py
   :language: python

Debugging
---------

When running libp2p you may want to see what things are happening behind the scenes. You can enable debug logging using the `LIBP2P_DEBUG` environment variable. This allows for fine-grained control over which modules log at which levels.

Basic Usage
~~~~~~~~~~~

To enable debug logging for all modules:

.. code:: bash

    # Method 1: Using export (persists for the shell session)
    # On Unix-like systems (Linux, macOS):
    export LIBP2P_DEBUG=DEBUG
    # On Windows (Command Prompt):
    set LIBP2P_DEBUG=DEBUG
    # On Windows (PowerShell):
    $env:LIBP2P_DEBUG="DEBUG"

    # Method 2: Setting for a single command
    # On Unix-like systems:
    LIBP2P_DEBUG=DEBUG python your_script.py
    # On Windows (Command Prompt):
    set LIBP2P_DEBUG=DEBUG && python your_script.py
    # On Windows (PowerShell):
    $env:LIBP2P_DEBUG="DEBUG"; python your_script.py

    # Method 3: Redirect logs to /dev/null to suppress console output
    # On Unix-like systems:
    LIBP2P_DEBUG=DEBUG python your_script.py 2>/dev/null
    # On Windows (Command Prompt):
    set LIBP2P_DEBUG=DEBUG && python your_script.py >nul 2>&1
    # On Windows (PowerShell):
    $env:LIBP2P_DEBUG="DEBUG"; python your_script.py *> $null

To enable debug logging for specific modules:

.. code:: bash

    # Debug logging for identity module only
    # On Unix-like systems:
    export LIBP2P_DEBUG=identity.identify:DEBUG
    # On Windows (Command Prompt):
    set LIBP2P_DEBUG=identity.identify:DEBUG
    # On Windows (PowerShell):
    $env:LIBP2P_DEBUG="identity.identify:DEBUG"

    # Multiple modules with different levels
    # On Unix-like systems:
    export LIBP2P_DEBUG=identity.identify:DEBUG,transport:INFO
    # On Windows (Command Prompt):
    set LIBP2P_DEBUG=identity.identify:DEBUG,transport:INFO
    # On Windows (PowerShell):
    $env:LIBP2P_DEBUG="identity.identify:DEBUG,transport:INFO"

Log Files
~~~~~~~~~

By default, logs are written to a file in the system's temporary directory with a timestamp and unique identifier. The file path is printed to stderr when logging starts.

When no custom log file is specified:
    - Logs are written to both a default file and to stderr (console output)
    - The default file path is printed to stderr when logging starts

When a custom log file is specified:
    - Logs are written only to the specified file
    - No console output is generated

To specify a custom log file location:

.. code:: bash

    # Method 1: Using export (persists for the shell session)
    # On Unix-like systems:
    export LIBP2P_DEBUG_FILE=/path/to/your/logfile.log
    # On Windows (Command Prompt):
    set LIBP2P_DEBUG_FILE=C:\path\to\your\logfile.log
    # On Windows (PowerShell):
    $env:LIBP2P_DEBUG_FILE="C:\path\to\your\logfile.log"

    # Method 2: Setting for a single command
    # On Unix-like systems:
    LIBP2P_DEBUG=DEBUG LIBP2P_DEBUG_FILE=/path/to/your/logfile.log python your_script.py
    # On Windows (Command Prompt):
    set LIBP2P_DEBUG=DEBUG && set LIBP2P_DEBUG_FILE=C:\path\to\your\logfile.log && python your_script.py
    # On Windows (PowerShell):
    $env:LIBP2P_DEBUG="DEBUG"; $env:LIBP2P_DEBUG_FILE="C:\path\to\your\logfile.log"; python your_script.py

Log Format
~~~~~~~~~~

Log messages follow this format:

.. code:: text

    timestamp - module_name - level - message

Example output:

.. code:: text

    2024-01-01 12:00:00,123 - libp2p.identity.identify - DEBUG - Starting identify protocol

What's Next
-----------

There are a lot of other concepts within `libp2p` that are not covered in this guide. For additional configuration options and examples, check out the :doc:`examples` guide. If you have any problems getting started, or if anything isn't clear, please let us know by submitting an issue!

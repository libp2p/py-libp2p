 Install
================

 Follow the steps below to install `py-libp2p` on your platform.

 **Recommended (using ``uv``, same as CI)**

 1. Install ``uv`` (if you don't have it yet):

    .. code:: sh

        curl -LsSf https://astral.sh/uv/install.sh | sh

 2. Create a Python virtual environment:

    .. code:: sh

        uv venv venv

 3. Activate the virtual environment:

    - **Linux / macOS**

      .. code:: sh

          source venv/bin/activate

    - **Windows (cmd)**

      .. code:: batch

          venv\Scripts\activate.bat

    - **Windows (PowerShell)**

      .. code:: powershell

          venv\Scripts\Activate.ps1

 4. Install `py-libp2p` from PyPI:

    .. code:: sh

        uv pip install libp2p

 **Alternative: using standard ``pip``**

 If you prefer not to use ``uv``, you can instead:

 1. Create a Python virtual environment:

    .. code:: sh

        python -m venv venv

 2. Activate the virtual environment (as shown above) and install:

    .. code:: sh

        python -m pip install libp2p

 Usage
-----
Configuration
~~~~~~~~~~~~~~
For all the information on how you can configure `py-libp2p`, TODO.

Limits
~~~~~~~~~~~~~~
For help configuring your node to resist malicious network peers, TODO.

Getting started
~~~~~~~~~~~~~~~~
If you are starting your journey with `py-libp2p`, read the :doc:`getting_started` guide.

Tutorials and Examples
~~~~~~~~~~~~~~~~~~~~~~~
You can find multiple examples in the :doc:`examples` guide that will help you understand how to use `py-libp2p` for various scenarios.

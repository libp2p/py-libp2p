Install
================

Follow the steps below to install `py-libp2p` on your platform.

Using uv (recommended)
~~~~~~~~~~~~~~~~~~~~~~

`uv <https://docs.astral.sh/uv/>`_ is a fast Python package manager.
It is used in py-libp2p's CI/CD pipeline and is the recommended way to install.

1. Install `uv` if you haven't already:

   .. code:: sh

       curl -LsSf https://astral.sh/uv/install.sh | sh

   Or using pip:

   .. code:: sh

       pip install uv

2. Create a virtual environment and install `py-libp2p`:

   .. code:: sh

       uv sync

   This automatically creates a ``.venv`` in the project directory and installs
   the package. Activate the environment to use it:

   - **Linux / macOS**

     .. code:: sh

         . .venv/bin/activate

   - **Windows (PowerShell)**

     .. code:: powershell

         .venv\Scripts\Activate.ps1

Using pip
~~~~~~~~~

If you prefer pip, you can install `py-libp2p` the traditional way:

1. Create a Python virtual environment:

   .. code:: sh

       python -m venv .venv

2. Activate the virtual environment:

   - **Linux / macOS**

     .. code:: sh

         . .venv/bin/activate

   - **Windows (cmd)**

     .. code:: batch

         .venv\Scripts\activate.bat

   - **Windows (PowerShell)**

     .. code:: powershell

         .venv\Scripts\Activate.ps1

3. Install `py-libp2p`:

   .. code:: sh

       pip install libp2p

Development Installation
~~~~~~~~~~~~~~~~~~~~~~~~

To install for development with all dev dependencies, use the ``dev`` dependency group:

.. code:: sh

    uv sync --group dev

For the full contributor environment setup (including pre-commit hooks), see
:doc:`contributing`.

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

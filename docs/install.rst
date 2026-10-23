Install
================

Follow the steps below to install `py-libp2p` on your platform.

.. note::

    py-libp2p installation is currently supported on Python versions ``<= 3.13``.

.. warning::

    **CA certificate security incident (October 2026).** Private keys for the
    eMudhra / emSign root and intermediate CAs were found to be insecure, so
    they have been removed from CA bundles. Upgrade your tooling *before*
    installing py-libp2p:

    - ``pip >= 26.2.2``. pip always adds its own bundled certifi on top of the
      system trust store, so an older pip keeps trusting the compromised
      certificates even when the OS store is fixed. Upgrade with
      ``python -m pip install --upgrade "pip>=26.2.2"``, or bootstrap from the
      checksummed wheel published in the PSF announcement.
    - ``uv >= 0.13.4``. Upgrade with ``UV_SYSTEM_CERTS=true uv self update``.
    - ``certifi >= 2026.10.19``. py-libp2p requires this version, so installing
      or upgrading py-libp2p pulls a CA bundle without the compromised
      certificates.
    - ``sigstore >= 4.5.1``, ``conda >= 26.9.4`` and ``pixi >= 0.82.1`` if you
      use them to install or verify packages.

    Rebuild container images with layer caching disabled so that the updated
    ``ca-certificates`` package is picked up. See the Python announcement
    `Information for Python users regarding the eMudhra / emSign CA certificate
    security incident
    <https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576>`__
    for the full advisory.

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

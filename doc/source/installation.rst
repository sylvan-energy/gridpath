.. _installation-section-ref:

************
Installation
************


Using a Terminal
================

To install GridPath, you will need to use a command-line interface. On Windows, you
can use cmd.exe, Windows PowerShell, or another command-line interface (we test using
cmd.exe, so recommend using that). You can search for cmd.exe from the Start menu. On
Mac, you can use the Terminal application. Search for it with Spotlight by clicking
the magnifying glass icon in the upper-right corner of the menu bar, or by pressing
Command-Space bar.


Requirements
============

Python
------

Running GridPath requires a Python 3 installation. GridPath is `tested nightly
<https://github.com/blue-marble/gridpath/actions/workflows/test_gridpath.yml>`__ in
Python 3.11, 3.12, 3.13, and 3.14. You can get Python `here <https://www.python.org/downloads/>`__.

.. _python-virtual-env-section-ref:

Python Virtual Environment
--------------------------
You must set up a Python virtual environment for GridPath to ensure
that the appropriate packages are installed and avoid interfering with the
requirements of other Python programs you may be using. Below are instructions for
how to set up a virtual environment using Python's *venv* module or with Anaconda.
Make sure to keep track of where your virtual environment directory is located, as you
will need to locate it if you are using the GridPath user interface. We will
refer to the GridPath Python environment directory as :code:`PATH/TO/PYTHON/ENV`.

^^^^
venv
^^^^
The `venv <https://docs.python.org/3/library/venv.html>`_ package is part of
the Python 3 standard library and is a lightweight method for managing
virtual environments. Once you have installed Python 3, you can create the
virtual environment for GridPath by running::

    python3 -m venv PATH/TO/PYTHON/ENV

This will create the virtual environment in the :code:`PATH/TO/PYTHON/ENV`
directory.

On Windows, you can activate the virtual environment by running appropriate
activation script from inside the Scripts directory of the virtual
environment directory.

From cmd.exe::

    C:\> PATH\TO\PYTHON\ENV\Scripts\activate.bat

On Linux-based systems including MacOS, use::

    source PATH/TO/PYTHON/ENV/bin/activate



Installing GridPath
===================

Before installing, make sure to activate your
:ref:`GridPath Python virtual environment<python-virtual-env-section-ref>`.

Installation from PyPi
----------------------

You can download and install the latest version of GridPath from PyPi with::

    pip install GridPath

To get a specific version, e.g., v0.16.0, use::

    pip install GridPath==0.16.0

Note that GridPath versions before 0.16.0 are not available on PyPi.

Installation from Source (Developers and Advanced Users)
--------------------------------------------------------

GridPath's source code is stored in a GitHub repository. You can find the latest
GridPath release `here <https://github.com/blue-marble/gridpath/releases/latest>`__.
Download the source code zip file and extract it. We will refer to the directory
where the code is extracted to as the :code:`PATH/TO/GRIDPATH` directory.

Most users should install GridPath by navigating to the GridPath directory
:code:`PATH/TO/GRIDPATH` with :code:`cd PATH/TO/GRIDPATH` and
running::

    pip install .


^^^^^^^^^^^^^^^^
Developer extras
^^^^^^^^^^^^^^^^

You may need to install additional packages if you plan to edit the GridPath code
and, for example, build the documentation from source, use the Black code formatter,
or check test coverage.

To install all packages, run::

    pip install -e .[all]

GridPath's developer extras can be installed individually. See the setup.py file in
the repository.

If you would like to edit the user-interface code, you will also need Node.js in
addition to Python and will be required to install various node packages.
See the User Interface section for more info.

Solver
======
You will need a solver to get optimization results. GridPath assumes you
will be using `HiGHS <https://highs.dev>`_ by default, but you can specify
a different solver as long as it is `supported by Pyomo
<https://pyomo.readthedocs
.io/en/latest/solving_pyomo_models.html#supported-solvers>`_,
e.g. Cbc, GLPK, CPLEX, Gurobi, etc.

HiGHS is installed automatically along with GridPath's other Python
dependencies (via the `highspy <https://pypi.org/project/highspy/>`_
package), so no additional setup is needed to use the default solver.

If you would like to use a different solver, e.g. `Cbc (Coin-or branch and
cut) <https://github.com/coin-or/Cbc#download>`__, GridPath allows you to
specify the location of the solver executable; to get it to be recognized,
automatically, you can also add it to your PATH system variables (see
instructions for Windows `here <https://www.java.com/en/download/help/path
.xml>`__).

Database
========
GridPath includes support for input and output data management via an SQLite
database. We also recommend `SQLite Studio <https://sqlitestudio.pl/index
.rvt>`_ as an SQLite database GUI.

We have implemented various tools to help you build your database. See the
:ref:`building-the-database-section-ref` section of the documentation
for more information.

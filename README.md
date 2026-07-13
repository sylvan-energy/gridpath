[![GridPath Test Suite Status](https://github.com/sylvan-energy/gridpath/actions/workflows/test_gridpath.yml/badge.svg?branch=main)](https://github.com/sylvan-energy/gridpath/actions/workflows/test_gridpath.yml)
[![Documentation Status](https://readthedocs.org/projects/gridpath/badge/?version=latest)](https://gridpath.readthedocs.io/en/latest/?badge=latest)
[![Coverage Status](https://coveralls.io/repos/github/sylvan-energy/gridpath/badge.svg?branch=main)](https://coveralls.io/github/sylvan-energy/gridpath?branch=main)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Lint Black](https://github.com/sylvan-energy/gridpath/actions/workflows/black.yml/badge.svg?branch=main)](https://github.com/sylvan-energy/gridpath/actions/workflows/black.yml)
[![DOI](https://zenodo.org/badge/65574330.svg)](https://doi.org/10.5281/zenodo.5822994)

# Welcome to GridPath

<p align="center" width="100%">
    <img src="https://github.com/sylvan-energy/gridpath/blob/main/doc/graphics/gridpath_logo.png?raw=true" width="20%"/>
</p>

![Approaches](https://github.com/sylvan-energy/gridpath/blob/main/doc/graphics/approaches.png?raw=true)


GridPath is a versatile power-system planning platform capable of a range of
planning approaches including production-cost, capacity-expansion, 
asset-valuation, and reliability modeling.

# Documentation
GridPath's documentation is hosted on [Read the Docs](https://gridpath.readthedocs.io/en/latest/).

# Installation

## Python
GridPath is tested on Python 3.11, 3.12, and 3.13. Get one of those Python 
versions [here](https://www.python.org/downloads/ "Python download").

## GridPath Python environment
You should create a Python environment for your GridPath installation, e.g. via 
`venv`, [a lightweight environment manager](https://docs.python.org/3/library/venv.html "venv") 
that is part of the standard Python distribution. Make sure to [create](https://docs.python.org/3/library/venv.html#creating-virtual-environments "create") and [activate](https://docs.python.org/3/library/venv.html#how-venvs-work "activate") the environment before installing GridPath.

## Install GridPath from PyPi

Once you have _created and activated_ the GridPath Python environment, you 
can install the latest version of GridPath from PyPi with:

```bash
pip install GridPath
```

## Install GridPath from source

You can alternatively download the GridPath source code and install from 
source.

```bash
pip install .[all]
```

**NOTE:** If you plan to edit the GridPath code, you should install with the `-e` flag.

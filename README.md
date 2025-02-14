# ao3-py

An unofficial python sdk for [Archive Of Our Own (AO3)](https://archiveofourown.org).

## Feature

- Completely type hint
- Object orient
- Lazy loading

## Quick Start

### Installation

#### Install from PYPI
```sh
pip install --no-cache --upgrade ao3-py
```

#### Install from Github

```sh
pip install --no-cache --upgrade git+https://github.com/OrganRemoved/ao3-py.git
```

or

```sh
pip install --no-cache --upgrade https://github.com/OrganRemoved/ao3-py/archive/refs/heads/main.zip
```

### Example
```python
from ao3 import AO3

client = AO3()

client.get_fandom(...)

client.get_tag(...)

client.get_work(...)
```

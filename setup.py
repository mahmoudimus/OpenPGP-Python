#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Setup the package OpenPGP-Python."""

from runpy import run_path

from setuptools import find_packages, setup

_INFO = run_path('src/OpenPGP/_meta.py')
_TEST_REQUIRES = [
    'mock',
    'pytest',
    'pytest-pycodestyle',
    'pytest-cov',
    'pytest-pydocstyle',
    'pytest-flake8',
    'pytest-isort',
    'pytest-mock',
    'pytest-pep8',
    'pytest-pylint',
    'pytest-black',
]

setup(
    # Metadata
    author=_INFO['__author__'],
    author_email=_INFO['__email__'],
    url=_INFO['__home__'],
    use_scm_version=True,
    zip_safe=False,
    # Package modules and data
    packages=find_packages('src'),
    package_dir={'': 'src'},
    # Requires
    python_requires='>=3.5',
    install_requires=[
        "pycryptodome",
    ],
    setup_requires=[
        'pytest-runner',
    ],
    tests_require=_TEST_REQUIRES,
    extras_require={
        'dev': _TEST_REQUIRES + [
            'flake8',
            'isort',
            'pylint<2.3.0',
            'black',
        ],
        'cryptography': [
            "cryptography<0.7",
            "cffi==0.8.6",
        ]
    },
    # PyPI Metadata
    keywords=['CLI'],
    platforms=['any'],
    classifiers=[
        # See: https://pypi.org/classifiers/
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'License :: OSI Approved :: MIT License',
    ]
)

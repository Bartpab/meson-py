[![codecov](https://codecov.io/bb/base_idfics/libdefi/branch/master/graph/badge.svg?token=TJIe09gEFd)](https://codecov.io/bb/base_idfics/libdefi) [ ![Codeship Status for base_idfics/libdefi](https://codeship.com/projects/305bee90-8976-0134-75f2-0e35097499a9/status?branch=master)](https://codeship.com/projects/184219)

### What is this repository for? ###

* The Core Library for the project Data Extract For IDFICS (DEFI)

  + IDFICS API Wrapper (Communication & Data Model)
  + Parser To IDFICS
  + DFD File parsing and processing
  + Excel Areva IRS parsing and processing
  + Some utils: Global Event Service with pub/sub pattern, Worker Threads, Base Converter, ...

### Code documentation ###
The entry point of the DEFI's lib documentation is located in ./doc/source/index.html.

### How do I get set up? ###

1. Run ``python setup.py install``

### Code coverage ###
DEFI library relies on *coverage.py* to produce code metrics in order to check
the coverage rate of the full project. To generate the report, you have to run within the root directory

``coverage run -m unittest``

This command will run all unit tests and produce a ``.coverage`` containing all the data about the coverage rate of each part of the project.

This report should be sent to [DEFI's lib codecov repository](https://codecov.io/bb/base_idfics/libdefi/) repository by running this command afterwards

``codecov --token=57ad36bc-6833-4ea0-9edd-94bea2224a7a``

### Contribution guidelines ###

Mainly, the contribution should be on increasing the coverage rate of the project.
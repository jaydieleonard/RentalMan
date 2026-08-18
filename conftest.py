"""Root conftest so `pytest` finds the `lib` package without any install step.

Its presence puts the project root on the import path, which is all the tests
need - everything under lib/ is pure Python with no database behind it.
"""

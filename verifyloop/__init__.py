"""verifyloop: the verification harness for bitask, layer 1.

It decides whether a C or C++ candidate compiles, runs without sanitizer
reports, and passes its tests. See SPEC.md for the design. Runtime code uses
the Python standard library only.
"""

import sys

if sys.version_info < (3, 12):  # fail with a clear message instead of an ImportError on StrEnum (audit V-02)
    raise RuntimeError("Melorin requires Python 3.12+ (found %s)" % sys.version.split()[0])

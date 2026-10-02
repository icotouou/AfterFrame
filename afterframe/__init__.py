"""AfterFrame - A borderless startup animation widget."""

# The one place the version is written down.
#
# constants.APP_VERSION is DERIVED from this, so the number the interface shows cannot
# drift from the package metadata again. It did drift: this said "0.1.0" while the corner
# of every page showed "V1.0", and since nothing read __version__ the mismatch was
# invisible until someone went looking.
#
# Bare number, no "v": the interface adds that prefix for display.
__version__ = "1.0"

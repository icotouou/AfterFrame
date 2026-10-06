"""AfterFrame - A borderless startup animation widget."""

# The one place the version is written down.
#
# constants derives two display forms from this: APP_VERSION, the full number, and
# APP_VERSION_SHORT, which drops the patch component for the two places that show it as
# decoration. So the number the interface shows cannot drift from the package metadata
# again. It did drift once: this said "0.1.0" while the corner of every page showed "V1.0",
# and because nothing read __version__ the mismatch was invisible until someone went looking.
#
# Bare number, no "v": the interface adds that prefix for display.
#
# Bump it when a batch of changes is worth calling a release, not after every commit.
__version__ = "1.0.1"

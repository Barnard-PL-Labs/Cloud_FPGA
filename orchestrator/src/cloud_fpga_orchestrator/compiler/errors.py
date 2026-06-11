class BuildError(Exception):
    """Base class for all build pipeline failures."""

    def __init__(self, stage: str, message: str, log: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.log = log


class AmaranthConversionError(BuildError):
    """Raised when Amaranth HDL fails to convert the user design to Verilog."""


class SoCMergeError(BuildError):
    """Raised when the user Verilog cannot be merged into the base LiteX SoC."""


class SynthesisError(BuildError):
    """Raised when Yosys fails to synthesize the merged design."""


class PlaceAndRouteError(BuildError):
    """Raised when nextpnr-ecp5 fails to place and route the netlist."""


class BitstreamPackError(BuildError):
    """Raised when ecppack fails to produce a bitstream from the routed config."""

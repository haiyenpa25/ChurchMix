"""
acoustic_measurement package:
- Dual-channel Transfer Function H1(f) = Syx(f) / Sxx(f)
- Coherence function gamma^2(f) for measurement reliability gating
- Impulse Response & Time-of-Flight / Delay Estimation via Cross-Correlation
- Multi-position spatial averaging with "No-Boost-in-Nulls" rule
- Open Sound Meter (OSM) and REW CSV/FRD Import & Export
"""

from .transfer_function import (
    TransferFunctionResult,
    compute_transfer_function,
    estimate_delay_samples,
    spatial_average_transfer_functions,
    filter_no_boost_nulls,
)
from .osm_importer import (
    AcousticMeasurementData,
    parse_osm_csv,
    export_osm_csv,
    parse_frd_file,
)

__all__ = [
    "TransferFunctionResult",
    "compute_transfer_function",
    "estimate_delay_samples",
    "spatial_average_transfer_functions",
    "filter_no_boost_nulls",
    "AcousticMeasurementData",
    "parse_osm_csv",
    "export_osm_csv",
    "parse_frd_file",
]

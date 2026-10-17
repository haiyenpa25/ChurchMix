"""
Open Sound Meter (OSM) & REW (Room EQ Wizard) CSV / FRD Importer and Exporter.
Allows the church sound engineer to import external acoustic measurements
and generate safe X32 PEQ profiles.
"""

from __future__ import annotations
import csv
import io
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import numpy as np


@dataclass
class AcousticMeasurementData:
    name: str
    freqs: np.ndarray        # Frequency in Hz
    magnitude_db: np.ndarray # Magnitude in dB
    phase_deg: np.ndarray    # Phase in degrees
    coherence: np.ndarray    # Coherence (0.0 to 1.0)
    metadata: Dict[str, Any] = field(default_factory=dict)


def parse_osm_csv(csv_content: str, name: str = "OSM_Measurement") -> AcousticMeasurementData:
    """
    Parse an Open Sound Meter CSV export.
    Standard OSM format:
    Frequency (Hz), Magnitude (dB), Phase (deg), Coherence
    """
    freqs = []
    mag = []
    phase = []
    coh = []

    reader = csv.reader(io.StringIO(csv_content.strip()))
    for row in reader:
        if not row or row[0].startswith('#') or row[0].startswith('Freq') or row[0].startswith('freq'):
            continue
        try:
            f = float(row[0])
            m = float(row[1])
            p = float(row[2]) if len(row) > 2 else 0.0
            c = float(row[3]) if len(row) > 3 else 1.0
            freqs.append(f)
            mag.append(m)
            phase.append(p)
            coh.append(c)
        except (ValueError, IndexError):
            continue

    if not freqs:
        raise ValueError("No valid frequency rows found in OSM CSV data")

    return AcousticMeasurementData(
        name=name,
        freqs=np.array(freqs, dtype=np.float32),
        magnitude_db=np.array(mag, dtype=np.float32),
        phase_deg=np.array(phase, dtype=np.float32),
        coherence=np.array(coh, dtype=np.float32),
        metadata={"source": "OpenSoundMeter", "row_count": len(freqs)},
    )


def parse_frd_file(frd_content: str, name: str = "FRD_Measurement") -> AcousticMeasurementData:
    """
    Parse standard 3-column FRD file (Frequency, Magnitude dB, Phase deg).
    """
    freqs = []
    mag = []
    phase = []

    for line in frd_content.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                f = float(parts[0])
                m = float(parts[1])
                p = float(parts[2]) if len(parts) > 2 else 0.0
                freqs.append(f)
                mag.append(m)
                phase.append(p)
            except ValueError:
                continue

    if not freqs:
        raise ValueError("No valid rows found in FRD data")

    return AcousticMeasurementData(
        name=name,
        freqs=np.array(freqs, dtype=np.float32),
        magnitude_db=np.array(mag, dtype=np.float32),
        phase_deg=np.array(phase, dtype=np.float32),
        coherence=np.ones(len(freqs), dtype=np.float32), # Default 1.0 when not present
        metadata={"source": "FRD", "row_count": len(freqs)},
    )


def export_osm_csv(data: AcousticMeasurementData) -> str:
    """Export AcousticMeasurementData to Open Sound Meter compatible CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["# Open Sound Meter Compatible Export - ChurchMix X32"])
    writer.writerow(["Frequency (Hz)", "Magnitude (dB)", "Phase (deg)", "Coherence"])

    for f, m, p, c in zip(data.freqs, data.magnitude_db, data.phase_deg, data.coherence):
        writer.writerow([round(float(f), 2), round(float(m), 2), round(float(p), 2), round(float(c), 3)])

    return output.getvalue()

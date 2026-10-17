// Shared meter rules. Missing/unmapped audio must never look like a hot X32 input.
export const finiteLevel = value => typeof value === 'number' && Number.isFinite(value);

export function meterPercent(value, floor = -60) {
  return finiteLevel(value) ? Math.max(0, Math.min(100, (value - floor) / -floor * 100)) : 0;
}

export function mixerMetersVerified(source) {
  return !!source?.valid && (source.simulated === true || source.mapping_verified === true);
}

export function safeMeterLevel(meter, source) {
  return mixerMetersVerified(source) && finiteLevel(meter?.meter_dbfs) ? meter.meter_dbfs : null;
}

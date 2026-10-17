import assert from 'node:assert/strict';
import { test } from 'node:test';
import { meterPercent, safeMeterLevel } from '../apps/web/js/signal-levels.js';

test('missing and invalid meters render empty, never full/red', () => {
  for (const value of [null, undefined, NaN, Infinity, '0']) assert.equal(meterPercent(value),0);
  assert.equal(meterPercent(-30),50);
  assert.equal(meterPercent(-120),0);
  assert.equal(meterPercent(3),100);
});
test('USB inputs cannot masquerade as named X32 channels without verified mapping', () => {
  const meter={meter_dbfs:-3};
  assert.equal(safeMeterLevel(meter,{valid:true,simulated:false,mapping_verified:false}),null);
  assert.equal(safeMeterLevel(meter,{valid:false,simulated:true}),null);
  assert.equal(safeMeterLevel(meter,{valid:true,simulated:true}),-3);
  assert.equal(safeMeterLevel(meter,{valid:true,simulated:false,mapping_verified:true}),-3);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { thermostatScenario, evScenario, solarScenario } from '../docs/behaviour.js';

test('setpoint 25 to 22 conserves temperature difference arithmetic', () => {
  const v=thermostatScenario({beforeC:25,afterC:22,outsideC:5,
    heatLossWK:200,heatedHours:14,fuel:'gas',efficiency:.85,priceP:8});
  assert.ok(Math.abs(v.differenceInput+8.4/.85)<1e-8);
  assert.ok(Math.abs(v.variableCostDifferenceDay+8.4/.85*.08)<1e-8);
  assert.equal(v.beforeHeat-v.afterHeat,8.4);
});
test('same setpoint has no energy difference',()=>{
 const v=thermostatScenario({beforeC:22,afterC:22,outsideC:5,
   heatLossWK:200,heatedHours:14,fuel:'heatpump',efficiency:3.2,priceP:26});
 assert.equal(v.differenceInput,0);
});
test('when outside is warmer than both setpoints, no heating demand',()=>{
 const v=thermostatScenario({beforeC:25,afterC:22,outsideC:30,
   heatLossWK:200,heatedHours:14,fuel:'resistive',efficiency:1,priceP:26});
 assert.equal(v.beforeInput,0); assert.equal(v.afterInput,0);
});
test('gas efficiency is limited to 100%',()=>{
 assert.throws(()=>thermostatScenario({beforeC:25,afterC:22,outsideC:5,
   heatLossWK:200,heatedHours:14,fuel:'gas',efficiency:3.5,priceP:8}));
});
test('EV costs respect home fraction, charger efficiency and cheap-hour share',()=>{
 const base={milesPerWeek:150,kwhPerMile:.28,chargingEfficiency:.9,
   homeFraction:1,offpeakFraction:.8,offpeakPriceP:10,daytimePriceP:26};
 const a=evScenario(base);
 assert.ok(Math.abs(a.annualGridKwh-150*.28/.9*52)<1e-8);
 assert.ok(Math.abs(a.averagePriceP-13.2)<1e-8);
 assert.equal(evScenario({...base,homeFraction:0}).annualGridKwh,0);
 assert.ok(evScenario({...base,offpeakFraction:0}).annualVariableCost>a.annualVariableCost);
});
test('solar decreases import but cannot change assumed gross demand',()=>{
 const x=solarScenario({kwp:4,yieldKwhPerKwpYear:900,selfUseShare:.45,
  annualHomeKwh:3500,importPriceP:26,exportPriceP:12});
 assert.equal(x.annualGenerationKwh,3600);
 assert.equal(x.selfConsumedKwh,1620);
 assert.equal(x.importAfterKwh,1880);
 assert.equal(x.exportedKwh,1980);
 assert.ok(Math.abs(x.yearlyVariableBillBenefit-(1620*.26+1980*.12))<1e-8);
});
test('solar cannot displace more import than actual demand',()=>{
 const x=solarScenario({kwp:10,yieldKwhPerKwpYear:1000,
   selfUseShare:1,annualHomeKwh:2000,importPriceP:26,exportPriceP:0});
 assert.equal(x.importAfterKwh,0);
 assert.equal(x.exportedKwh,8000);
});
test('bad inputs are rejected',()=>{
 assert.throws(()=>solarScenario({kwp:-1,yieldKwhPerKwpYear:800,
   selfUseShare:.5,annualHomeKwh:1000,importPriceP:26,exportPriceP:12}));
 assert.throws(()=>evScenario({milesPerWeek:100,kwhPerMile:.25,chargingEfficiency:0,
  homeFraction:1,offpeakFraction:.5,offpeakPriceP:10,daytimePriceP:26}));
});

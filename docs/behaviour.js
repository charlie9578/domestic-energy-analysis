/** Scenario arithmetic; all inputs are user assumptions, not measured household effects. */
const num=(v,n,min,max)=>{const x=Number(v);if(!Number.isFinite(x)||x<min||x>max)throw Error(n+' outside valid range');return x};
export function thermostatScenario({beforeC,afterC,outsideC,heatLossWK,heatedHours,fuel,efficiency,priceP}){
 const before=num(beforeC,'Before setpoint',5,35),after=num(afterC,'After setpoint',5,35);
 const outside=num(outsideC,'Outside temperature',-30,45),heatLoss=num(heatLossWK,'Heat loss',1,1000);
 const hours=num(heatedHours,'Heating hours',0,24),eff=num(efficiency,'Efficiency',.1,8);
 if(!['gas','heatpump','resistive'].includes(fuel)||fuel==='gas'&&eff>1||fuel==='resistive'&&eff!==1)throw Error('Invalid heating fuel or efficiency');
 const price=num(priceP,'Price',0,200);
 const beforeHeat=heatLoss*hours*Math.max(0,before-outside)/1000;
 const afterHeat=heatLoss*hours*Math.max(0,after-outside)/1000;
 const beforeInput=beforeHeat/eff,afterInput=afterHeat/eff;
 return {beforeHeat,afterHeat,beforeInput,afterInput,differenceInput:afterInput-beforeInput,variableCostDifferenceDay:(afterInput-beforeInput)*price/100};
}
export function evScenario({milesPerWeek,kwhPerMile,chargingEfficiency,homeFraction,offpeakFraction,offpeakPriceP,daytimePriceP}){
 const miles=num(milesPerWeek,'Miles',0,1000),specific=num(kwhPerMile,'EV kWh per mile',.1,1),eff=num(chargingEfficiency,'Charger efficiency',.5,1);
 const share=num(homeFraction,'Home fraction',0,1),night=num(offpeakFraction,'Offpeak fraction',0,1);
 const low=num(offpeakPriceP,'Night rate',-10,200),high=num(daytimePriceP,'Day rate',-10,200);
 const weeklyGridKwh=miles*specific*share/eff,averagePriceP=night*low+(1-night)*high;
 return {weeklyGridKwh,annualGridKwh:weeklyGridKwh*52,averagePriceP,annualVariableCost:weeklyGridKwh*52*averagePriceP/100};
}
export function solarScenario({kwp,yieldKwhPerKwpYear,selfUseShare,annualHomeKwh,importPriceP,exportPriceP}){
 const gen=num(kwp,'PV size',0,30)*num(yieldKwhPerKwpYear,'PV yield',100,1500);
 const self=num(selfUseShare,'Self use fraction',0,1),home=num(annualHomeKwh,'Annual load',0,250000);
 const importPrice=num(importPriceP,'Import rate',-10,200),exportPrice=num(exportPriceP,'Export rate',-10,200);
 const selfConsumedKwh=Math.min(gen*self,home),exportedKwh=gen-selfConsumedKwh;
 const avoidedImportValue=selfConsumedKwh*importPrice/100,exportValue=exportedKwh*exportPrice/100;
 return {annualGenerationKwh:gen,selfConsumedKwh,exportedKwh,importBeforeKwh:home,importAfterKwh:home-selfConsumedKwh,
 avoidedImportValue,exportValue,yearlyVariableBillBenefit:avoidedImportValue+exportValue};
}
const el=id=>document.getElementById(id), value=id=>Number(el(id).value);
const set=(id,t)=>{el(id).textContent=t};
const gbp=n=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format(n);
const fmt=(n,d=1)=>new Intl.NumberFormat('en-GB',{maximumFractionDigits:d}).format(n);
const bar=(id,v,max)=>{el(id).style.width=(100*Math.max(0,Math.min(1,v/(max||1))))+'%'};
function render(){
 try{
  const fuel=el('fuel').value,eff=fuel==='gas'?value('boiler-eff')/100:fuel==='heatpump'?value('heatpump-cop'):1;
  const rate=fuel==='gas'?value('gas-price'):value('elec-price');
  const h=thermostatScenario({beforeC:value('thermostat-from'),afterC:value('thermostat-to'),outsideC:value('outdoor'),
    heatLossWK:value('heat-loss'),heatedHours:value('heated-hours'),fuel,efficiency:eff,priceP:rate});
  for(const [id,t] of [['thermostat-from-value',value('thermostat-from')+'°C'],['thermostat-to-value',value('thermostat-to')+'°C'],['outdoor-value',value('outdoor')+'°C'],
   ['heat-loss-value',value('heat-loss')+' W/K'],['heated-hours-value',value('heated-hours')+' h'],['boiler-eff-value',value('boiler-eff')+'%'],
   ['heatpump-cop-value',fmt(value('heatpump-cop'))],['heating-before',fmt(h.beforeInput)+' kWh/day'],['heating-after',fmt(h.afterInput)+' kWh/day'],
   ['heating-difference',(h.differenceInput<0?'−':'+')+fmt(Math.abs(h.differenceInput))+' kWh/day'],
   ['heating-money',(h.variableCostDifferenceDay<0?'Saving ':'Extra cost ')+gbp(Math.abs(h.variableCostDifferenceDay)*30)+' over 30 identical-weather days'],
   ['heat-fuel-label',fuel==='gas'?'gas input':fuel==='heatpump'?'heat pump electricity':'resistance electricity']])set(id,t);
  el('boiler-eff-label').hidden=fuel!=='gas';el('heatpump-cop-label').hidden=fuel!=='heatpump';
  const hm=Math.max(1,h.beforeInput,h.afterInput);bar('heating-bar-before',h.beforeInput,hm);bar('heating-bar-after',h.afterInput,hm);
  const ev=evScenario({milesPerWeek:value('ev-miles'),kwhPerMile:value('ev-kwh-mile'),chargingEfficiency:value('ev-eff')/100,
   homeFraction:value('ev-at-home')/100,offpeakFraction:value('ev-offpeak-share')/100,offpeakPriceP:value('night-price'),daytimePriceP:value('elec-price')});
  for(const [id,t] of [['ev-miles-value',value('ev-miles')+' miles'],['ev-at-home-value',value('ev-at-home')+'%'],['ev-offpeak-value',value('ev-offpeak-share')+'%'],
    ['ev-annual-energy',fmt(ev.annualGridKwh,0)+' kWh/year'],['ev-annual-cost',gbp(ev.annualVariableCost)+' additional annual variable electricity cost'],
    ['ev-cheap',fmt(ev.averagePriceP)+' p/kWh average effective rate']])set(id,t);
  const pv=solarScenario({kwp:value('pv-kwp'),yieldKwhPerKwpYear:value('pv-yield'),selfUseShare:value('pv-self')/100,
    annualHomeKwh:value('annual-baseline'),importPriceP:value('elec-price'),exportPriceP:value('export-price')});
  for(const [id,t] of [['pv-size-value',value('pv-kwp')+' kWp'],['pv-self-value',value('pv-self')+'%'],
   ['pv-generation',fmt(pv.annualGenerationKwh,0)+' kWh/year generated'],
   ['pv-grid-import',fmt(pv.importAfterKwh,0)+' kWh/year grid import, versus '+fmt(pv.importBeforeKwh,0)+' before'],
   ['pv-benefit',gbp(pv.yearlyVariableBillBenefit)+' annual variable-bill benefit'],
   ['pv-breakdown',gbp(pv.avoidedImportValue)+' avoided import + '+gbp(pv.exportValue)+' export credit'],
   ['pv-baseline-label','100%'],['pv-reduced-label',fmt(100*pv.importAfterKwh/Math.max(1,pv.importBeforeKwh),0)+'%']])set(id,t);
  const max=Math.max(1,pv.importBeforeKwh);bar('pv-bar-before',pv.importBeforeKwh,max);bar('pv-bar-after',pv.importAfterKwh,max);
  set('change-error','');
 }catch(e){set('change-error',e.message)}
}
if(typeof document!=='undefined'){
 const form=el('change-controls');
 if(form){form.addEventListener('submit',event=>event.preventDefault());form.addEventListener('input',render);form.addEventListener('change',render);render()}
}


/** Turn a local Python report into safe display records. Never treats the
 * estimated association as causal and never sends local files to a server. */
export function summariseInterventionReport(input){
 if(!input || typeof input !== 'object' || Array.isArray(input))throw Error('Expected a JSON results object');
 let records=[];
 if(typeof input.event_date==='string')records=[input];
 else if(Array.isArray(input.results))records=input.results;
 else if(input.sequential && Array.isArray(input.sequential.results))records=input.sequential.results;
 else if(input.sequential_interventions && Array.isArray(input.sequential_interventions.results))records=input.sequential_interventions.results;
 else if(input.examples && typeof input.examples==='object')records=Object.values(input.examples);
 else if(input.single_event_scenarios && typeof input.single_event_scenarios==='object')records=Object.values(input.single_event_scenarios);
 else throw Error('No intervention results found. Export from behaviour_change evaluate/timeline or run_behaviour_study.');
 if(!records.length)throw Error('This file has no intervention records.');
 return records.map((r,i)=>{
  if(!r || typeof r!=='object')throw Error('Malformed result '+i);
  const hasEstimate=Number.isFinite(r.deviation_observed_minus_expected_kwh) &&
                    Number.isFinite(r.deviation_kwh_per_observed_day);
  const warnings=Array.isArray(r.warnings)?r.warnings.filter(w=>typeof w==='string'):[];
  const bins=Array.isArray(r.change_over_time_30_day_bins)?
   r.change_over_time_30_day_bins.filter(b=>Number.isFinite(b.deviation_kwh_per_observed_day)&&
       Number.isFinite(b.days_since_event_start)):[];
  return {
    eventDate:typeof r.event_date==='string'?r.event_date:'Unknown',
    eventType:typeof r.event_type==='string'?r.event_type:Array.isArray(r.event_types)?r.event_types.join(' + '):'Unknown',
    status:hasEstimate?'Descriptive association only':String(r.status||'Not assessable'),
    meterBoundary:String(r.meter_boundary||input.meter_boundary||'Not specified'),
    beforeDays:Number.isInteger(r.n_pre_days)?r.n_pre_days:null,
    afterDays:Number.isInteger(r.n_post_days)?r.n_post_days:null,
    baseline:hasEstimate&&Number.isFinite(r.weather_adjusted_expected_post_kwh)?r.weather_adjusted_expected_post_kwh:null,
    observed:hasEstimate&&Number.isFinite(r.observed_post_kwh)?r.observed_post_kwh:null,
    delta:hasEstimate?r.deviation_observed_minus_expected_kwh:null,
    deltaPerDay:hasEstimate?r.deviation_kwh_per_observed_day:null,
    validationMae:r.validation&&Number.isFinite(r.validation.validation_mae_kwh_day)?r.validation.validation_mae_kwh_day:null,
    reliability:String(r.reliability_flag||'Check underlying model and input metadata'),
    warnings,bins,
    explanation:String(r.explanation||'The baseline is modelled from pre-event data; this is not a causal savings estimate.')
  };
 });
}
function showLocalReport(raw){
 const root=el('uploaded-results');if(!root)return;
 root.replaceChildren();
 const records=summariseInterventionReport(raw);
 const title=document.createElement('p');
 title.textContent=raw.provenance||raw.dataset_classification||'Source label not supplied. Confirm whether data are measured or synthetic.';
 root.append(title);
 for(const record of records){
  const card=document.createElement('article');card.className='card';
  const heading=document.createElement('h3');
  heading.textContent=record.eventDate+' · '+record.eventType+' · '+record.status;card.append(heading);
  const detail=document.createElement('p');
  detail.textContent='Meter: '+record.meterBoundary+' · Days before/after: '+
    (record.beforeDays??'—')+'/'+(record.afterDays??'—')+' · Reliability: '+record.reliability;
  card.append(detail);
  if(record.delta!==null){
   const line=document.createElement('p');
   line.textContent='Measured minus weather-expected: '+fmt(record.delta)+' kWh across recorded post days ('+
     fmt(record.deltaPerDay,2)+' kWh per observed day). Pre-event validation MAE: '+
     (record.validationMae!==null?fmt(record.validationMae,2)+' kWh/day':'not available')+'.';
   card.append(line);
   const summary=document.createElement('p');
   summary.textContent='Expected post: '+fmt(record.baseline)+' kWh; observed post: '+fmt(record.observed)+' kWh.';
   card.append(summary);
  }else{
   const reason=document.createElement('p');reason.textContent=record.explanation;card.append(reason);
  }
  if(record.bins.length){
   const table=document.createElement('table'),head=document.createElement('thead'),row=document.createElement('tr');
   for(const h of ['Days since change','Difference (kWh/day)']){
    const th=document.createElement('th');th.textContent=h;row.append(th)
   }
   head.append(row);table.append(head);
   const body=document.createElement('tbody');
   for(const bin of record.bins){
    const tr=document.createElement('tr');
    for(const value of [bin.days_since_event_start+'–'+(bin.days_since_event_start+29),
                         fmt(bin.deviation_kwh_per_observed_day,2)]){
      const td=document.createElement('td');td.textContent=value;tr.append(td)
    }
    body.append(tr);
   }
   table.append(body);card.append(table);
  }
  if(record.warnings.length){
   const h=document.createElement('p');h.textContent='Warnings: '+record.warnings.join(' · ');card.append(h)
  }
  root.append(card);
 }
}
if(typeof document!=='undefined'){
 const upload=el('report-file');
 if(upload)upload.addEventListener('change',async()=>{
   const status=el('report-status');
   const file=upload.files?.[0];
   if(!file){status.textContent='No file selected.';el('uploaded-results').replaceChildren();return}
   if(file.size>10*1024*1024){status.textContent='File too large (10 MB local viewer limit).';return}
   try{
    const report=JSON.parse(await file.text());
    showLocalReport(report);
    status.textContent='Loaded locally from '+file.name+'. No data transmitted by this viewer.';
   }catch(err){el('uploaded-results').replaceChildren();status.textContent='Cannot read report: '+err.message}
 });
}

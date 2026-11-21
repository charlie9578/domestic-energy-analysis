"use strict";

const gbp = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });
const tariffForm = document.querySelector("#tariff-form");

tariffForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const rates = new FormData(tariffForm);
  const flat = Math.round(546.956 * Number(rates.get("flat")));
  const dayNight = Math.round(446.580 * Number(rates.get("day")) + 100.376 * Number(rates.get("night")));

  document.querySelector("#flat-cost").textContent = gbp.format(flat / 100);
  document.querySelector("#tou-cost").textContent = gbp.format(dayNight / 100);
  const difference = dayNight - flat;
  document.querySelector("#tariff-verdict").textContent = difference === 0
    ? "The tariffs cost the same to the nearest penny."
    : `${difference > 0 ? "Flat" : "Day and night"} is ${gbp.format(Math.abs(difference) / 100)} cheaper.`;
});

// Annual modelled bills in pence from research/SCENARIO_STUDY.md, section B.
const bills = {
  flat: { baseline: 232965, solar: 191688, insulation: 217836, heatPump: 224269,
    battery: 178567, thermal: 385325, combined: 137473 },
  tou: { baseline: 204327, solar: 159648, insulation: 189198, heatPump: 205381,
    battery: 157385, thermal: 330061, combined: 102532 },
};
const upgradeForm = document.querySelector("#upgrade-form");

function updateUpgrade() {
  const inputs = new FormData(upgradeForm);
  const tariff = bills[inputs.get("tariff")];
  const selected = tariff[inputs.get("portfolio")];
  const difference = selected - tariff.baseline;

  document.querySelector("#baseline-bill").textContent = gbp.format(tariff.baseline / 100);
  document.querySelector("#upgrade-bill").textContent = gbp.format(selected / 100);
  document.querySelector("#upgrade-verdict").textContent = difference === 0
    ? "Same annual bill before installation costs."
    : `${gbp.format(Math.abs(difference) / 100)} ${difference > 0 ? "higher" : "lower"} per year before installation costs.`;
}

upgradeForm?.addEventListener("change", updateUpgrade);
if (upgradeForm) updateUpgrade();

import { api } from "../api.js";
import { esc } from "../format.js";
import { formatNumber, getLanguage, getLanguagePreference, getLanguages, setLanguagePreference, t } from "../i18n.js";
import { icon } from "../icons.js";
import { syncPushLanguage } from "../push.js";
import { emit, loadInverters, on, saveSettings, state } from "../state.js";
import { getThemePreference, setThemePreference } from "../theme.js";
import { emptyState, field, readForm, switchInput, toast } from "../ui.js";
import { bindInverterForm, inverterFormHtml } from "./inverter-form.js";
import { bindTariffForm, tariffFormHtml, today } from "./tariff-form.js";

export const SECTIONS = [
  { id: "inverters", icon: "inverter" },
  { id: "alerts", icon: "bell" },
  { id: "tariff", icon: "euro" },
  { id: "location", icon: "pin" },
  { id: "data", icon: "database" },
  { id: "appearance", icon: "palette" },
  { id: "about", icon: "info" },
];

// ---------- Sections bound to /api/settings ----------

function settingsForm(body) {
  return `
    <form class="form settings-form" novalidate>
      ${body}
      <div class="save-bar" hidden>
        <span>${esc(t("settings.unsaved"))}</span>
        <div class="button-row">
          <button type="button" class="btn btn-ghost" data-action="discard">${esc(t("common.discard"))}</button>
          <button type="submit" class="btn btn-primary">${icon("check")}${esc(t("common.save"))}</button>
        </div>
      </div>
    </form>`;
}

function bindSettingsForm(form, rerender) {
  const bar = form.querySelector(".save-bar");
  const snapshot = JSON.stringify(readForm(form));
  const check = () => {
    bar.hidden = JSON.stringify(readForm(form)) === snapshot;
  };
  form.addEventListener("input", check);
  form.addEventListener("change", check);
  form.querySelector('[data-action="discard"]').addEventListener("click", rerender);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const values = Object.fromEntries(Object.entries(readForm(form)).filter(([, v]) => v !== null));
    try {
      await saveSettings(values);
      toast(t("settings.saved"));
      rerender();
    } catch (error) {
      toast(t("common.save_failed", { detail: error.message }), "error");
    }
  });
}

const s = (key) => state.settings[key];

function alertCard({ kind, iconName, enabledKey, body, warning = "" }) {
  const enabled = Boolean(s(enabledKey));
  return `
    <section class="card alert-card">
      <div class="alert-card-head">
        <span class="alert-icon kind-${kind}">${icon(iconName)}</span>
        <div class="grow">
          <h3>${esc(t(`alerts.${kind}.name`))}</h3>
          <p class="muted small">${esc(t(`alerts.${kind}.description`))}</p>
        </div>
        ${switchInput(enabledKey, enabled, t(`alerts.${kind}.name`))}
      </div>
      <div class="alert-card-body" ${enabled ? "" : "hidden"}>
        ${warning}
        <div class="form-grid">${body}</div>
      </div>
    </section>`;
}

function alertsSection() {
  const missingLocation = s("latitude") == null || s("longitude") == null;
  return settingsForm(`
    ${alertCard({
      kind: "overload",
      iconName: "bolt",
      enabledKey: "alert_overload_enabled",
      body:
        field({ label: t("settings.alerts.contracted_power"), name: "alert_overload_limit_w", dataType: "int", value: s("alert_overload_limit_w"), suffix: "W", attrs: "required min=100 max=100000 step=100" }) +
        field({ label: t("settings.alerts.alert_after"), name: "alert_overload_minutes", value: s("alert_overload_minutes"), suffix: "min", hint: t("settings.alerts.overload_after_hint"), attrs: "required min=0 max=120 step=0.5" }),
    })}
    ${alertCard({
      kind: "no_production",
      iconName: "sun",
      enabledKey: "alert_no_pv_enabled",
      warning: missingLocation
        ? `<a class="notice" href="#/settings/location">${icon("pin")}<span>${esc(t("settings.alerts.needs_location"))}</span>${icon("chevronRight")}</a>`
        : "",
      body:
        field({ label: t("settings.alerts.alert_after"), name: "alert_no_pv_minutes", value: s("alert_no_pv_minutes"), suffix: "min", attrs: "required min=1 max=600 step=1" }) +
        field({ label: t("settings.alerts.pv_below"), name: "alert_no_pv_threshold_w", dataType: "int", value: s("alert_no_pv_threshold_w"), suffix: "W", attrs: "required min=0 max=10000 step=10" }) +
        field({ label: t("settings.alerts.sun_above"), name: "alert_no_pv_min_sun_elevation_deg", value: s("alert_no_pv_min_sun_elevation_deg"), suffix: "°", hint: t("settings.alerts.sun_above_hint"), attrs: "required min=0 max=60 step=1" }),
    })}
    ${alertCard({
      kind: "offline",
      iconName: "wifiOff",
      enabledKey: "alert_offline_enabled",
      body: field({ label: t("settings.alerts.alert_after"), name: "alert_offline_minutes", value: s("alert_offline_minutes"), suffix: "min", attrs: "required min=1 max=600 step=1" }),
    })}
    <p class="muted small">${esc(t("settings.alerts.notifications_hint"))} <a href="#/alerts">${esc(t("settings.alerts.notifications_link"))}</a></p>
  `);
}

function locationSection() {
  return settingsForm(`
    <section class="card location-card">
      <p class="muted">${esc(t("settings.location.description"))}</p>
      <div class="form-grid">
        ${field({ label: t("settings.location.latitude"), name: "latitude", value: s("latitude") ?? "", suffix: "°", attrs: "min=-90 max=90 step=0.0001" })}
        ${field({ label: t("settings.location.longitude"), name: "longitude", value: s("longitude") ?? "", suffix: "°", attrs: "min=-180 max=180 step=0.0001" })}
      </div>
      <button type="button" class="btn" data-action="locate">${icon("location")}${esc(t("settings.location.use_device"))}</button>
    </section>
  `);
}

function dataSection() {
  return settingsForm(`
    <section class="card">
      <div class="form-grid">
        ${field({ label: t("settings.data.recorder_interval"), name: "recorder_interval_seconds", value: s("recorder_interval_seconds"), suffix: "s", hint: t("settings.data.recorder_interval_hint"), attrs: "required min=10 max=3600" })}
        ${field({ label: t("settings.data.retention"), name: "retention_days", dataType: "int", value: s("retention_days"), suffix: t("settings.data.days"), hint: t("settings.data.retention_hint"), attrs: "required min=0 max=3650" })}
        ${field({ label: t("settings.data.downsample"), name: "downsample_after_days", dataType: "int", value: s("downsample_after_days"), suffix: t("settings.data.days"), hint: t("settings.data.downsample_hint"), attrs: "required min=0 max=3650" })}
        ${field({ label: t("settings.data.timezone"), name: "timezone", type: "text", dataType: "text", value: s("timezone"), hint: t("settings.data.timezone_hint"), attrs: "required" })}
      </div>
    </section>
  `);
}

// ---------- Device-only sections ----------

function appearanceSection() {
  const lang = getLanguagePreference();
  const theme = getThemePreference();
  return `
    <section class="card">
      <p class="muted small">${esc(t("settings.appearance.device_only"))}</p>
      <label class="field">
        <span class="field-label">${esc(t("settings.appearance.language"))}</span>
        <span class="input-wrap"><select data-action="language">
          <option value="auto" ${lang === "auto" ? "selected" : ""}>${esc(t("settings.appearance.language_auto"))}</option>
          ${getLanguages().map((l) => `<option value="${esc(l.code)}" ${lang === l.code ? "selected" : ""}>${esc(l.name)}</option>`).join("")}
        </select></span>
      </label>
      <div class="field">
        <span class="field-label">${esc(t("settings.appearance.theme"))}</span>
        <div class="segmented" role="radiogroup">
          ${["system", "light", "dark"]
            .map((v) => `<button type="button" role="radio" data-theme-value="${v}" class="${theme === v ? "active" : ""}" aria-checked="${theme === v}">${icon(v === "dark" ? "moon" : v === "light" ? "sun" : "palette")}${esc(t(`settings.appearance.theme_${v}`))}</button>`)
            .join("")}
        </div>
      </div>
    </section>`;
}

function aboutSection(pushDevices) {
  return `
    <section class="card about">
      <img src="/static/icon.svg" alt="" width="56" height="56" />
      <div>
        <h3>Grid Monitor</h3>
        <p class="muted">${esc(t("settings.about.version", { version: state.version || "?" }))}</p>
      </div>
    </section>
    <section class="card">
      <dl class="facts">
        <div><dt>${esc(t("settings.about.inverters"))}</dt><dd>${state.inverters.length}</dd></div>
        <div><dt>${esc(t("settings.about.push_devices"))}</dt><dd>${pushDevices ?? "--"}</dd></div>
      </dl>
      <a class="btn btn-ghost" href="/docs" target="_blank" rel="noopener">${esc(t("settings.about.api_docs"))}</a>
    </section>`;
}

// ---------- Inverters ----------

function inverterCard(inverter) {
  const driver = state.drivers.find((d) => d.id === inverter.driver_id);
  return `
    <section class="card inverter-card" data-id="${inverter.id}">
      <div class="inverter-head">
        <span class="alert-icon">${icon("inverter")}</span>
        <div class="grow">
          <h3>${esc(inverter.name)} ${inverter.enabled ? "" : `<span class="pill">${esc(t("inverters.disabled"))}</span>`}</h3>
          <p class="muted small">${esc(driver ? driver.name : inverter.driver_id)} · ${esc(inverter.host)}:${esc(inverter.port)}${
            inverter.serial_number ? ` · ${esc(t("inverters.serial", { serial: inverter.serial_number }))}` : ""
          }</p>
        </div>
        <button type="button" class="icon-btn" data-action="edit" aria-label="${esc(t("common.edit"))}">${icon("edit")}</button>
        <button type="button" class="icon-btn danger" data-action="delete" aria-label="${esc(t("common.delete"))}">${icon("trash")}</button>
      </div>
      <div class="inverter-edit"></div>
    </section>`;
}

function renderInverters(container) {
  container.innerHTML = `
    <div class="stack">
      ${state.inverters.length ? state.inverters.map(inverterCard).join("") : emptyState("inverter", t("inverters.none"))}
      <section class="card add-card" hidden></section>
      <button type="button" class="btn btn-primary" data-action="add">${icon("plus")}${esc(t("inverters.add"))}</button>
    </div>`;

  const addCard = container.querySelector(".add-card");
  const addButton = container.querySelector('[data-action="add"]');
  const refresh = async () => {
    await loadInverters();
    renderInverters(container);
  };

  addButton.addEventListener("click", () => {
    addCard.hidden = false;
    addButton.hidden = true;
    addCard.innerHTML = `<h3>${esc(t("inverters.add_title"))}</h3>${inverterFormHtml()}`;
    bindInverterForm(addCard.querySelector("form"), { onSaved: refresh, onCancel: () => renderInverters(container) });
  });

  container.querySelectorAll(".inverter-card").forEach((card) => {
    const inverter = state.inverters.find((item) => item.id === Number(card.dataset.id));
    const edit = card.querySelector(".inverter-edit");
    card.querySelector('[data-action="edit"]').addEventListener("click", () => {
      if (edit.innerHTML) {
        edit.innerHTML = "";
        return;
      }
      edit.innerHTML = inverterFormHtml(inverter);
      bindInverterForm(edit.querySelector("form"), {
        inverter,
        onSaved: refresh,
        onCancel: () => {
          edit.innerHTML = "";
        },
      });
    });
    card.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      if (!window.confirm(t("inverters.delete_confirm", { inverter: inverter.name }))) return;
      try {
        await api.del(`/api/inverters/${inverter.id}`);
        toast(t("inverters.deleted"));
        await refresh();
        if (!state.inverters.length) window.location.hash = "#/setup";
      } catch (error) {
        toast(t("common.delete_failed", { detail: error.message }), "error");
      }
    });
  });
}

// ---------- Tariff ----------

function tariffDate(value) {
  return new Date(`${value}T00:00:00`).toLocaleDateString(getLanguage(), { day: "numeric", month: "long", year: "numeric" });
}

function tariffCard(tariff, current) {
  const prices = ["p1", "p2", "p3"].map((p) => formatNumber(tariff[`energy_price_${p}`], 3)).join(" / ");
  return `
    <section class="card inverter-card" data-id="${tariff.id}">
      <div class="inverter-head">
        <span class="alert-icon">${icon("receipt")}</span>
        <div class="grow">
          <h3>${esc(t("tariff.from", { date: tariffDate(tariff.valid_from) }))} ${current ? `<span class="pill">${esc(t("tariff.current"))}</span>` : ""}</h3>
          <p class="muted small tariff-summary">${esc(prices)} €/kWh · ${esc(formatNumber(tariff.contracted_power_p1_kw, 2))} kW</p>
        </div>
        <button type="button" class="icon-btn" data-action="edit" aria-label="${esc(t("common.edit"))}">${icon("edit")}</button>
        <button type="button" class="icon-btn danger" data-action="delete" aria-label="${esc(t("common.delete"))}">${icon("trash")}</button>
      </div>
      <div class="inverter-edit"></div>
    </section>`;
}

async function renderTariffs(container) {
  let tariffs;
  try {
    tariffs = await api.get("/api/tariffs");
  } catch (error) {
    container.innerHTML = emptyState("alert", t("tariff.load_failed"), error.message);
    return;
  }
  const current = tariffs.find((item) => item.valid_from <= today());
  container.innerHTML = `
    <div class="stack">
      ${settingsForm(`
        <section class="card">
          <div class="form-grid">
            ${field({ label: t("tariff.billing_day"), name: "billing_day", dataType: "int", value: s("billing_day"), hint: t("tariff.billing_day_hint"), attrs: "required min=1 max=28" })}
          </div>
        </section>`)}
      <h3 class="section-title">${esc(t("tariff.list_title"))}</h3>
      ${tariffs.length ? tariffs.map((item) => tariffCard(item, item === current)).join("") : emptyState("euro", t("tariff.none"), t("tariff.none_text"))}
      <section class="card add-card" hidden></section>
      <button type="button" class="btn btn-primary" data-action="add">${icon("plus")}${esc(t("tariff.add"))}</button>
    </div>`;

  const refresh = () => renderTariffs(container);
  bindSettingsForm(container.querySelector(".settings-form"), refresh);

  const addCard = container.querySelector(".add-card");
  const addButton = container.querySelector('[data-action="add"]');
  addButton.addEventListener("click", () => {
    addCard.hidden = false;
    addButton.hidden = true;
    addCard.innerHTML = `<h3>${esc(t("tariff.add_title"))}</h3>${tariffFormHtml(null, tariffs[0])}`;
    bindTariffForm(addCard.querySelector("form"), { onSaved: refresh, onCancel: refresh });
  });

  container.querySelectorAll(".inverter-card").forEach((card) => {
    const tariff = tariffs.find((item) => item.id === Number(card.dataset.id));
    const edit = card.querySelector(".inverter-edit");
    card.querySelector('[data-action="edit"]').addEventListener("click", () => {
      if (edit.innerHTML) {
        edit.innerHTML = "";
        return;
      }
      edit.innerHTML = tariffFormHtml(tariff);
      bindTariffForm(edit.querySelector("form"), {
        tariff,
        onSaved: refresh,
        onCancel: () => {
          edit.innerHTML = "";
        },
      });
    });
    card.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      if (!window.confirm(t("tariff.delete_confirm", { date: tariffDate(tariff.valid_from) }))) return;
      try {
        await api.del(`/api/tariffs/${tariff.id}`);
        toast(t("tariff.deleted"));
        await refresh();
      } catch (error) {
        toast(t("common.delete_failed", { detail: error.message }), "error");
      }
    });
  });
}

// ---------- Page ----------

export function renderSettings(root, section) {
  const wide = window.matchMedia("(min-width: 900px)").matches;
  if (!section && wide) section = "inverters";
  if (section && !SECTIONS.some((item) => item.id === section)) section = null;

  root.innerHTML = `
    <div class="page settings ${section ? "has-section" : ""}">
      <nav class="settings-nav" aria-label="${esc(t("nav.settings"))}">
        ${SECTIONS.map(
          (item) => `
          <a href="#/settings/${item.id}" class="settings-link ${item.id === section ? "active" : ""}">
            <span class="settings-link-icon">${icon(item.icon)}</span>
            <span class="grow"><strong>${esc(t(`settings.sections.${item.id}.title`))}</strong>
            <small>${esc(t(`settings.sections.${item.id}.subtitle`))}</small></span>
            ${icon("chevronRight", "icon chevron")}
          </a>`
        ).join("")}
      </nav>
      <div class="settings-content">
        ${
          section
            ? `<a class="back-link" href="#/settings">${icon("chevronLeft")}${esc(t("nav.settings"))}</a>
               <h2 class="section-heading">${esc(t(`settings.sections.${section}.title`))}</h2>
               <div class="section-body"></div>`
            : ""
        }
      </div>
    </div>`;

  if (!section) return () => {};
  const body = root.querySelector(".section-body");
  const rerender = () => renderSection();

  function renderSection() {
    if (section === "inverters") {
      renderInverters(body);
      return;
    }
    if (section === "tariff") {
      renderTariffs(body);
      return;
    }
    if (section === "appearance") {
      body.innerHTML = appearanceSection();
      body.querySelector('[data-action="language"]').addEventListener("change", async (event) => {
        await setLanguagePreference(event.target.value);
        await syncPushLanguage();
        emit("language");
      });
      body.querySelectorAll("[data-theme-value]").forEach((button) =>
        button.addEventListener("click", () => {
          setThemePreference(button.dataset.themeValue);
          renderSection();
        })
      );
      return;
    }
    if (section === "about") {
      body.innerHTML = aboutSection(null);
      api
        .get("/api/push/public-key")
        .then((info) => {
          body.innerHTML = aboutSection(info.subscriptions);
        })
        .catch(() => {});
      return;
    }

    body.innerHTML = { alerts: alertsSection, location: locationSection, data: dataSection }[section]();
    const form = body.querySelector("form");
    bindSettingsForm(form, rerender);

    form.querySelectorAll(".alert-card").forEach((card) => {
      const toggle = card.querySelector('.alert-card-head input[type="checkbox"]');
      toggle.addEventListener("change", () => {
        card.querySelector(".alert-card-body").hidden = !toggle.checked;
      });
    });

    form.querySelector('[data-action="locate"]')?.addEventListener("click", () => {
      if (!("geolocation" in navigator)) {
        toast(t("settings.location.unavailable"), "error");
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          form.elements.latitude.value = pos.coords.latitude.toFixed(4);
          form.elements.longitude.value = pos.coords.longitude.toFixed(4);
          form.dispatchEvent(new Event("input"));
        },
        () => toast(t("settings.location.failed"), "error"),
        { enableHighAccuracy: false, timeout: 10000 }
      );
    });
  }

  renderSection();
  const off = on("inverters", () => {
    if (section === "about") renderSection();
  });
  return off;
}

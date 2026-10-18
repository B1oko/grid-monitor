import { api } from "../api.js";
import { discoverInverters } from "../discovery.js";
import { esc } from "../format.js";
import { t } from "../i18n.js";
import { icon } from "../icons.js";
import { state } from "../state.js";
import { field, readForm, switchInput, toast } from "../ui.js";

const POLL_OPTIONS = [1, 2, 5, 10, 30];

export function inverterFormHtml(inverter = null) {
  const isNew = !inverter;
  const value = (key, fallback = "") => (inverter ? inverter[key] ?? fallback : fallback);
  return `
    <form class="form inverter-form" novalidate>
      ${
        isNew
          ? `<div class="scan-box">
              <button type="button" class="btn" data-action="scan">${icon("search")}${esc(t("inverters.scan"))}</button>
              <span class="muted small" data-v="scan-status">${esc(t("inverters.scan_hint"))}</span>
              <div class="candidates" data-v="candidates"></div>
            </div>`
          : ""
      }
      <div class="form-grid">
        ${field({ label: t("inverters.name"), name: "name", type: "text", dataType: "text", value: value("name", t("inverters.default_name")), attrs: "required maxlength=120" })}
        ${
          isNew
            ? `<label class="field"><span class="field-label">${esc(t("inverters.driver"))}</span>
                <span class="input-wrap"><select name="driver_id" data-type="text">
                  ${state.drivers.map((d) => `<option value="${esc(d.id)}">${esc(d.name)} (${esc(d.id)})</option>`).join("")}
                </select></span></label>`
            : ""
        }
        ${field({ label: t("inverters.host"), name: "host", type: "text", dataType: "text", value: value("host"), hint: t("inverters.host_hint"), attrs: 'required placeholder="192.168.1.50"' })}
        ${field({ label: t("inverters.port"), name: "port", dataType: "int", value: value("port", 502), attrs: "required min=1 max=65535" })}
        ${field({ label: t("inverters.unit_id"), name: "unit_id", dataType: "int", value: value("unit_id", 1), attrs: "required min=1 max=255" })}
        <label class="field"><span class="field-label">${esc(t("inverters.poll_interval"))}</span>
          <span class="input-wrap has-suffix"><select name="poll_interval_s" data-type="num">
            ${POLL_OPTIONS.map((s) => `<option value="${s}" ${Number(value("poll_interval_s", 2)) === s ? "selected" : ""}>${s}</option>`).join("")}
          </select><span class="suffix">s</span></span>
          <span class="field-hint">${esc(t("inverters.poll_interval_hint"))}</span>
        </label>
        ${field({ label: t("inverters.battery_capacity"), name: "battery_capacity_kwh", value: value("battery_capacity_kwh", ""), suffix: "kWh", hint: t("inverters.battery_capacity_hint"), attrs: 'min=0 step=0.1' })}
      </div>
      ${
        isNew
          ? ""
          : `<div class="row-between">
              <span>${esc(t("inverters.enabled"))}</span>${switchInput("enabled", inverter.enabled, t("inverters.enabled"))}
            </div>`
      }
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">${icon("check")}${esc(t(isNew ? "inverters.add" : "common.save"))}</button>
        <button type="button" class="btn btn-ghost" data-action="cancel">${esc(t("common.cancel"))}</button>
      </div>
    </form>`;
}

export function bindInverterForm(form, { inverter = null, onSaved, onCancel }) {
  const scan = form.querySelector('[data-action="scan"]');
  if (scan) {
    scan.addEventListener("click", async () => {
      const status = form.querySelector('[data-v="scan-status"]');
      const list = form.querySelector('[data-v="candidates"]');
      scan.disabled = true;
      list.innerHTML = "";
      try {
        const candidates = await discoverInverters((text) => {
          status.textContent = text;
        });
        list.innerHTML = candidates
          .map((c, i) => {
            const known = c.serial_number && state.inverters.find((item) => item.serial_number === c.serial_number);
            const details = [c.driver_id, `${Math.round(c.latency_ms)} ms`];
            if (c.serial_number) details.push(t("inverters.serial", { serial: c.serial_number }));
            if (known) details.push(t("inverters.already_added", { inverter: known.name }));
            return `<button type="button" class="candidate" data-i="${i}">
              ${icon("inverter")}<span><strong>${esc(c.host)}:${esc(c.port)}</strong>
              <small>${esc(details.join(" · "))}</small></span></button>`;
          })
          .join("");
        list.querySelectorAll("[data-i]").forEach((button) =>
          button.addEventListener("click", () => {
            const c = candidates[Number(button.dataset.i)];
            form.elements.host.value = c.host;
            form.elements.port.value = c.port;
            if (form.elements.driver_id) form.elements.driver_id.value = c.driver_id;
            list.querySelectorAll(".candidate").forEach((b) => b.classList.toggle("selected", b === button));
          })
        );
      } catch (error) {
        status.textContent = t("discovery.error", { detail: error.message });
      }
      scan.disabled = false;
    });
  }

  form.querySelector('[data-action="cancel"]')?.addEventListener("click", () => onCancel?.());

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const values = readForm(form);
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      const saved = inverter
        ? await api.patch(`/api/inverters/${inverter.id}`, values)
        : await api.post("/api/inverters", { ...values, enabled: true });
      toast(t(inverter ? "inverters.saved" : "inverters.added"));
      await onSaved?.(saved);
    } catch (error) {
      toast(t("common.save_failed", { detail: error.message }), "error");
      submit.disabled = false;
    }
  });
}

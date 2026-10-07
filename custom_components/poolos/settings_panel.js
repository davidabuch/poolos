const DOMAIN = "poolos";
const POOL_OS_DASHBOARD_PATH = "/pool-os";

const LABELS = {
  filtration_scheduling_mode: "Filtration strategy",
  preferred_filtration_catchup_start: "TOU catch-up start",
  traditional_filtration_start: "Traditional filtration start",
  pump_filtration_unit: "Filtration pump target",
  pump_filtration_rpm: "Filtration RPM",
  pump_filtration_gpm: "Filtration flow",
  pump_solar_heating_unit: "Solar heating pump target",
  pump_solar_heating_rpm: "Solar heating RPM",
  pump_solar_heating_gpm: "Solar heating flow",
  pump_gas_heating_unit: "Gas heating pump target",
  pump_gas_heating_rpm: "Gas heating RPM",
  pump_gas_heating_gpm: "Gas heating flow",
  pump_temperature_probe_unit: "Temperature probe target",
  pump_temperature_probe_rpm: "Temperature probe RPM",
  pump_temperature_probe_gpm: "Temperature probe flow",
  pump_priming_rpm: "Priming RPM",
  pump_grid_outage_rpm: "Grid outage RPM",
  spa_solar_roof_f: "Spa Solar roof threshold",
  sanitation_unit: "Sanitation pump target",
  sanitation_rpm: "Sanitation RPM",
  sanitation_gpm: "Sanitation flow",
  pool_sanitation_duration_minutes: "Pool sanitation duration",
  hot_tub_sanitation_duration_minutes: "Hot Tub sanitation duration",
  diagnostics_enabled: "Diagnostics enabled",
  grid_status_entity: "Grid status entity",
  grid_outage_simulation_entity: "Grid outage simulation entity",
  pool_thermostat_entity: "Pool thermostat entity",
  spa_thermostat_entity: "Hot Tub thermostat entity",
  pump_rpm_entity: "Pump RPM entity",
  pump_gpm_entity: "Pump flow entity",
  pump_power_entity: "Pump power entity",
  water_temperature_entity: "Water temperature entity",
  solar_temperature_entity: "Solar roof temperature entity",
  air_temperature_entity: "Air temperature entity",
  solar_active_entity: "Solar active entity",
  heater_active_entity: "Heater active entity",
  pool_command_entity: "Pool command entity",
  spa_command_entity: "Hot Tub command entity",
  waterfall_active_entity: "Waterfall active entity",
  jets_active_entity: "Jets active entity",
  slide_active_entity: "Slide active entity",
  pool_light_entity: "Pool light entity",
  intellicenter_host: "IntelliCenter host",
  intellicenter_transport: "IntelliCenter transport",
};

const numberSelector = (min, max, step, unit) => ({
  selector: {
    number: {
      min,
      max,
      step,
      mode: "box",
      unit_of_measurement: unit,
    },
  },
});

const entitySelector = (domain) => ({
  selector: {
    entity: {
      domain: Array.isArray(domain) ? domain : [domain],
      multiple: false,
      reorder: false,
    },
  },
});

const timeSelector = () => ({ selector: { time: {} } });

const unitSelector = (gpmSupported) => ({
  selector: {
    select: {
      options: [
        { value: "rpm", label: "RPM" },
        ...(gpmSupported ? [{ value: "gpm", label: "GPM" }] : []),
      ],
      mode: "dropdown",
      multiple: false,
      custom_value: false,
    },
  },
});

const gpmSelector = (capability) => numberSelector(
  Number(capability?.minimum_gpm ?? 1),
  Number(capability?.maximum_gpm ?? 200),
  1,
  "gpm",
);

const buildSchema = (capabilities = {}) => {
  const filtrationGpm = capabilities.filtration ?? {};
  const solarGpm = capabilities.solar_heating ?? {};
  const gasGpm = capabilities.gas_heating ?? {};
  const probeGpm = capabilities.temperature_probe ?? {};
  const sanitationGpm = capabilities.sanitation ?? {};
  return [
  {
    type: "expandable",
    name: "filtration",
    title: "Filtration",
    icon: "mdi:water-sync",
    expanded: true,
    flatten: true,
    schema: [
      {
        name: "filtration_scheduling_mode",
        required: true,
        selector: {
          select: {
            options: [
              { value: "solar_tou_optimized", label: "Solar / TOU Optimized" },
              { value: "traditional_time_based", label: "Traditional Time-Based" },
            ],
            mode: "dropdown",
            multiple: false,
            custom_value: false,
          },
        },
      },
      {
        name: "preferred_filtration_catchup_start",
        required: true,
        ...timeSelector(),
        visible: {
          field: "filtration_scheduling_mode",
          operator: "eq",
          value: "solar_tou_optimized",
        },
      },
      {
        name: "traditional_filtration_start",
        required: true,
        ...timeSelector(),
        visible: {
          field: "filtration_scheduling_mode",
          operator: "eq",
          value: "traditional_time_based",
        },
      },
      {
        name: "pump_filtration_unit",
        required: true,
        ...unitSelector(Boolean(filtrationGpm.supported)),
      },
      {
        name: "pump_filtration_rpm",
        required: true,
        ...numberSelector(450, 3450, 10, "rpm"),
        visible: {
          field: "pump_filtration_unit",
          operator: "eq",
          value: "rpm",
        },
      },
      {
        name: "pump_filtration_gpm",
        required: true,
        ...gpmSelector(filtrationGpm),
        visible: {
          field: "pump_filtration_unit",
          operator: "eq",
          value: "gpm",
        },
      },
    ],
  },
  {
    type: "expandable",
    name: "thermal",
    title: "Thermal",
    icon: "mdi:thermometer-water",
    expanded: true,
    flatten: true,
    schema: [
      {
        name: "spa_solar_roof_f",
        required: true,
        ...numberSelector(110, 150, 1, "°F"),
      },
      {
        name: "pump_solar_heating_unit",
        required: true,
        ...unitSelector(Boolean(solarGpm.supported)),
      },
      {
        name: "pump_solar_heating_rpm",
        required: true,
        ...numberSelector(450, 3450, 10, "rpm"),
        visible: {
          field: "pump_solar_heating_unit",
          operator: "eq",
          value: "rpm",
        },
      },
      {
        name: "pump_solar_heating_gpm",
        required: true,
        ...gpmSelector(solarGpm),
        visible: {
          field: "pump_solar_heating_unit",
          operator: "eq",
          value: "gpm",
        },
      },
      {
        name: "pump_gas_heating_unit",
        required: true,
        ...unitSelector(Boolean(gasGpm.supported)),
      },
      {
        name: "pump_gas_heating_rpm",
        required: true,
        ...numberSelector(450, 3450, 10, "rpm"),
        visible: {
          field: "pump_gas_heating_unit",
          operator: "eq",
          value: "rpm",
        },
      },
      {
        name: "pump_gas_heating_gpm",
        required: true,
        ...gpmSelector(gasGpm),
        visible: {
          field: "pump_gas_heating_unit",
          operator: "eq",
          value: "gpm",
        },
      },
      {
        name: "pump_temperature_probe_unit",
        required: true,
        ...unitSelector(Boolean(probeGpm.supported)),
      },
      {
        name: "pump_temperature_probe_rpm",
        required: true,
        ...numberSelector(450, 3450, 10, "rpm"),
        visible: {
          field: "pump_temperature_probe_unit",
          operator: "eq",
          value: "rpm",
        },
      },
      {
        name: "pump_temperature_probe_gpm",
        required: true,
        ...gpmSelector(probeGpm),
        visible: {
          field: "pump_temperature_probe_unit",
          operator: "eq",
          value: "gpm",
        },
      },
    ],
  },
  {
    type: "expandable",
    name: "pump",
    title: "Pump & Safety",
    icon: "mdi:pump",
    flatten: true,
    schema: [
      {
        name: "pump_priming_rpm",
        required: true,
        ...numberSelector(450, 3450, 10, "rpm"),
      },
      {
        name: "pump_grid_outage_rpm",
        required: true,
        ...numberSelector(450, 3450, 10, "rpm"),
      },
    ],
  },
  {
    type: "expandable",
    name: "sanitation",
    title: "Sanitation",
    icon: "mdi:shimmer",
    flatten: true,
    schema: [
      {
        name: "sanitation_unit",
        required: true,
        ...unitSelector(Boolean(sanitationGpm.supported)),
      },
      {
        name: "sanitation_rpm",
        required: true,
        ...numberSelector(450, 3450, 10, "rpm"),
        visible: {
          field: "sanitation_unit",
          operator: "eq",
          value: "rpm",
        },
      },
      {
        name: "sanitation_gpm",
        required: true,
        ...gpmSelector(sanitationGpm),
        visible: {
          field: "sanitation_unit",
          operator: "eq",
          value: "gpm",
        },
      },
      {
        name: "pool_sanitation_duration_minutes",
        required: true,
        ...numberSelector(30, 1440, 5, "min"),
      },
      {
        name: "hot_tub_sanitation_duration_minutes",
        required: true,
        ...numberSelector(30, 1440, 5, "min"),
      },
    ],
  },
  {
    type: "expandable",
    name: "hardware",
    title: "Entity & Hardware Mapping",
    icon: "mdi:connection",
    flatten: true,
    schema: [
      { name: "grid_status_entity", required: true, ...entitySelector("binary_sensor") },
      {
        name: "grid_outage_simulation_entity",
        required: false,
        ...entitySelector("input_boolean"),
      },
      { name: "pool_thermostat_entity", required: false, ...entitySelector("climate") },
      { name: "spa_thermostat_entity", required: false, ...entitySelector("climate") },
      { name: "pump_rpm_entity", required: false, ...entitySelector("sensor") },
      { name: "pump_gpm_entity", required: false, ...entitySelector("sensor") },
      { name: "pump_power_entity", required: false, ...entitySelector("sensor") },
      { name: "water_temperature_entity", required: false, ...entitySelector("sensor") },
      { name: "solar_temperature_entity", required: false, ...entitySelector("sensor") },
      { name: "air_temperature_entity", required: false, ...entitySelector("sensor") },
      {
        name: "solar_active_entity",
        required: false,
        ...entitySelector(["binary_sensor", "switch"]),
      },
      {
        name: "heater_active_entity",
        required: false,
        ...entitySelector(["binary_sensor", "switch"]),
      },
      {
        name: "pool_command_entity",
        required: false,
        ...entitySelector(["binary_sensor", "switch"]),
      },
      {
        name: "spa_command_entity",
        required: false,
        ...entitySelector(["binary_sensor", "switch"]),
      },
      {
        name: "waterfall_active_entity",
        required: false,
        ...entitySelector(["binary_sensor", "switch"]),
      },
      {
        name: "jets_active_entity",
        required: false,
        ...entitySelector(["binary_sensor", "switch"]),
      },
      {
        name: "slide_active_entity",
        required: false,
        ...entitySelector(["binary_sensor", "switch"]),
      },
      { name: "pool_light_entity", required: false, ...entitySelector("light") },
    ],
  },
  {
    type: "expandable",
    name: "advanced",
    title: "Advanced",
    icon: "mdi:tune-variant",
    flatten: true,
    schema: [
      { name: "diagnostics_enabled", required: true, type: "boolean" },
      {
        name: "intellicenter_host",
        required: false,
        selector: { text: { type: "text" } },
      },
      {
        name: "intellicenter_transport",
        required: true,
        selector: {
          select: {
            options: [
              { value: "tcp", label: "TCP" },
              { value: "websocket", label: "WebSocket" },
            ],
            mode: "dropdown",
            multiple: false,
            custom_value: false,
          },
        },
      },
    ],
  },
  ];
};

class PoolOSSettingsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._panel = null;
    this._data = null;
    this._initial = null;
    this._loading = false;
    this._saving = false;
    this._message = "";
    this._capabilities = {};
  }

  set hass(value) {
    const first = !this._hass;
    this._hass = value;
    if (first && this.isConnected) {
      this._load();
    }
    this._syncForm();
  }

  get hass() {
    return this._hass;
  }

  set panel(value) {
    this._panel = value;
  }

  set narrow(_value) {}
  set route(_value) {}

  connectedCallback() {
    this._render();
    if (this._hass && !this._data) {
      this._load();
    }
  }

  async _load() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._message = "";
    this._render();
    try {
      const response = await this._hass.connection.sendMessagePromise({
        type: "poolos/settings/get",
      });
      this._data = { ...response.settings };
      this._initial = JSON.stringify(this._data);
      this._version = response.version;
      this._capabilities = { ...(response.pump_target_capabilities ?? {}) };
    } catch (err) {
      this._message = `Unable to load PoolOS settings: ${err?.message ?? err}`;
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _save() {
    if (!this._hass || !this._data || this._saving) return;
    this._saving = true;
    this._message = "Saving settings…";
    this._render();
    try {
      const response = await this._hass.connection.sendMessagePromise({
        type: "poolos/settings/update",
        settings: this._data,
      });
      this._data = { ...response.settings };
      this._initial = JSON.stringify(this._data);
      this._capabilities = { ...(response.pump_target_capabilities ?? this._capabilities) };
      this._message = "Saved. PoolOS is reloading with the new configuration.";
    } catch (err) {
      this._message = `Save failed: ${err?.message ?? err}`;
    } finally {
      this._saving = false;
      this._render();
    }
  }

  _dirty() {
    return this._data && JSON.stringify(this._data) !== this._initial;
  }

  _render() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          min-height: 100%;
          background: var(--primary-background-color);
          color: var(--primary-text-color);
          box-sizing: border-box;
        }
        .page {
          max-width: 980px;
          margin: 0 auto;
          padding: 24px 16px 48px;
        }
        .header {
          margin: 0 0 20px;
        }
        h1 {
          font-size: 28px;
          font-weight: 500;
          margin: 0 0 6px;
        }
        .subtle {
          color: var(--secondary-text-color);
          line-height: 1.45;
        }
        ha-card {
          display: block;
          padding: 8px 20px 20px;
        }
        .actions {
          position: sticky;
          bottom: 0;
          margin-top: 16px;
          padding: 14px 0 4px;
          display: flex;
          gap: 12px;
          align-items: center;
          flex-wrap: wrap;
          background: linear-gradient(
            to bottom,
            transparent,
            var(--primary-background-color) 28%
          );
        }
        button {
          border: 0;
          border-radius: 20px;
          padding: 10px 22px;
          font: inherit;
          font-weight: 500;
          cursor: pointer;
          background: var(--primary-color);
          color: var(--text-primary-color, white);
        }
        button.secondary {
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }
        button:disabled {
          opacity: .45;
          cursor: default;
        }
        .message {
          color: var(--secondary-text-color);
          font-size: 14px;
          min-height: 20px;
        }
        .loading {
          padding: 24px 0;
          color: var(--secondary-text-color);
        }
      </style>
      <div class="page">
        <div class="header">
          <h1>PoolOS Settings</h1>
          <div class="subtle">
            Configure PoolOS by subsystem. Only settings applicable to the selected
            operating strategy are shown. Version ${this._version ?? this._panel?.config?.version ?? ""}.
          </div>
        </div>
        <ha-card>
          <div id="content">
            ${this._loading || !this._data ? '<div class="loading">Loading PoolOS configuration…</div>' : '<ha-form id="form"></ha-form>'}
          </div>
        </ha-card>
        <div class="actions">
          <button id="save" ${!this._dirty() || this._saving ? "disabled" : ""}>Save</button>
          <button id="reload" class="secondary" ${this._saving ? "disabled" : ""}>Reload</button>
          <button id="dashboard" class="secondary">Back to PoolOS Dashboard</button>
          <span class="message">${this._message}</span>
        </div>
      </div>
    `;

    const save = this.shadowRoot.getElementById("save");
    const reload = this.shadowRoot.getElementById("reload");
    const dashboard = this.shadowRoot.getElementById("dashboard");
    if (save) save.addEventListener("click", () => this._save());
    if (reload) reload.addEventListener("click", () => this._load());
    if (dashboard) dashboard.addEventListener("click", () => window.location.assign(POOL_OS_DASHBOARD_PATH));
    this._syncForm();
  }

  _syncForm() {
    if (!this.shadowRoot || !this._hass || !this._data) return;
    const form = this.shadowRoot.getElementById("form");
    if (!form) return;
    form.hass = this._hass;
    form.data = this._data;
    form.schema = buildSchema(this._capabilities);
    form.computeLabel = (schema) => LABELS[schema.name] ?? schema.title ?? schema.name;
    if (!form._poolosBound) {
      form._poolosBound = true;
      form.addEventListener("value-changed", (event) => {
        this._data = { ...event.detail.value };
        form.data = this._data;
        this._message = "";
        this._updateActions();
      });
    }
  }

  _updateActions() {
    if (!this.shadowRoot) return;
    const save = this.shadowRoot.getElementById("save");
    const message = this.shadowRoot.querySelector(".message");
    if (save) {
      save.disabled = !this._dirty() || this._saving;
    }
    if (message) {
      message.textContent = this._message;
    }
  }
}

const moduleUrl = new URL(import.meta.url);
const assetVersion = (moduleUrl.searchParams.get("v") ?? "current")
  .replace(/[^a-zA-Z0-9_-]/g, "-")
  .toLowerCase();
const elementName = `poolos-settings-panel-${assetVersion.slice(-12)}`;
if (!customElements.get(elementName)) {
  customElements.define(elementName, PoolOSSettingsPanel);
}

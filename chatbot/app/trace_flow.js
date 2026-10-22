const ServiceIcon = {
  props: { service: String, icons: Object },
  template: `
    <span v-if="service === 'lumen' || icons[service]" class="tf-service-icon"
          :class="'tf-service-icon--' + service" aria-hidden="true">
      <img v-if="icons[service]" :src="icons[service]" alt="" draggable="false">
    </span>`,
};

export default {
  components: { ServiceIcon },
  props: { flow: Object, icons: Object, traceId: String, labEnabled: Boolean, messages: Object, locale: String, initialSelectedId: String },
  data() { return { selectedId: this.initialSelectedId || this.flow.calls[0]?.id, filter: "all", returns: true,
    inspection: null, inspecting: false, loading: false, inspectionError: "", sectionKey: "", copied: "",
    workbench: false, templateId: "", draft: null, sending: false, replayResult: null, replayError: "", exported: "",
    requestGeneration: 0, controller: null, expiryTimer: null,
    decisionOpen: false, vaultDecision: null, decisionLoading: false, decisionError: "",
    decisionGeneration: 0, decisionController: null }; },
  mounted() {
    this.onVisibility = () => { if (document.hidden) { this.hideSensitive(); this.closeVaultDecision(); } };
    document.addEventListener("visibilitychange", this.onVisibility);
    if (this.initialSelectedId) this.$nextTick(() => this.$refs.diagram?.querySelector('[aria-pressed="true"]')?.scrollIntoView({block: "nearest"}));
  },
  beforeUnmount() {
    this.hideSensitive();
    this.closeVaultDecision();
    document.removeEventListener("visibilitychange", this.onVisibility);
  },
  computed: {
    requestTemplate() { return this.inspection?.requests?.find(r => r.id === this.templateId); },
    visible() { return this.flow.calls.filter(c => this.filter === "all" || c.target === this.filter); },
    selected() { return this.visible.find(c => c.id === this.selectedId) || this.visible[0]; },
    position() { return this.visible.findIndex(c => c.id === this.selected?.id); },
    section() { return this.inspection?.sections.find(s => s.key === this.sectionKey); },
    personal() { return this.selected?.personal; },
    personalOutcome() {
      if (this.selected?.target !== 'vault') return 'Este paso corresponde a Verify. Su HTTP 200 no demuestra acceso al secreto; selecciona la llamada a Vault.';
      if (this.selected.http_status === 403) return 'Vault ha denegado esta operación. La comparación de rutas explica el aislamiento; el HTTP 403 por sí solo no identifica todas las reglas que intervinieron.';
      if (this.selected.http_status === 200) return this.personal?.path_matches_owner === false
        ? 'Vault ha permitido una ruta ajena. Revisa otras políticas o cambios de configuración; la política personal mostrada no explica ese permiso.'
        : 'Vault ha permitido esta operación. Además de la ruta propia, el techo del agente y el RAR debían permitirla.';
      return 'Este resultado no confirma acceso ni aislamiento: puede ser un secreto inexistente, un conflicto de versión u otro error. Consulta la respuesta real.';
    },
  },
  methods: {
    t(text, values = {}) {
      const translated = this.messages?.[text] || text;
      return translated.replace(/\{(\w+)\}/g, (match, key) => Object.hasOwn(values, key) ? String(values[key]) : match);
    },
    actor(id) { return this.flow.actors.find(a => a.id === id)?.name || id; },
    x(id) { return (this.flow.actors.findIndex(a => a.id === id) + 0.5) * 1000 / this.flow.actors.length; },
    ms(value) { return new Intl.NumberFormat(this.locale || "es-ES", { maximumFractionDigits: 2 }).format(value) + " ms"; },
    select(call) { if (call.id !== this.selectedId) { this.hideSensitive(); this.closeVaultDecision(); } this.selectedId = call.id; },
    format(value) { return typeof value === "string" ? value : JSON.stringify(value, null, 2); },
    closeVaultDecision() {
      this.decisionGeneration++; this.decisionController?.abort();
      this.decisionOpen = false; this.vaultDecision = null; this.decisionLoading = false; this.decisionError = "";
    },
    async toggleVaultDecision() {
      if (this.decisionOpen) { this.closeVaultDecision(); return; }
      if (this.selected?.target !== 'vault') return;
      this.decisionOpen = true; this.decisionLoading = true; this.decisionError = "";
      const generation = ++this.decisionGeneration, sid = this.selected.id;
      this.decisionController = new AbortController();
      try {
        const response = await fetch(`/traces/${encodeURIComponent(this.traceId)}/steps/${encodeURIComponent(sid)}/vault-decision`,
          {credentials: "same-origin", cache: "no-store", signal: this.decisionController.signal});
        const data = await response.json();
        if (generation !== this.decisionGeneration || sid !== this.selected?.id) return;
        if (response.ok) this.vaultDecision = data;
        else this.decisionError = this.t(data.message || 'No se pudo consultar la auditoría.');
      } catch (error) {
        if (error.name !== 'AbortError' && generation === this.decisionGeneration)
          this.decisionError = this.t('No se pudo consultar la auditoría.');
      } finally { if (generation === this.decisionGeneration) this.decisionLoading = false; }
    },
    retryVaultDecision() { this.closeVaultDecision(); return this.toggleVaultDecision(); },
    hideSensitive() {
      this.requestGeneration++;
      this.controller?.abort();
      clearTimeout(this.expiryTimer);
      this.inspection = null; this.inspecting = false; this.loading = false;
      this.inspectionError = ""; this.sectionKey = ""; this.copied = "";
      this.workbench = false; this.draft = null; this.templateId = ""; this.replayResult = null; this.replayError = ""; this.sending = false; this.exported = "";
    },
    async revealSensitive() {
      this.hideSensitive();
      const generation = this.requestGeneration, sid = this.selected?.id;
      this.inspecting = true; this.loading = true;
      this.controller = new AbortController();
      try {
        const response = await fetch(`/traces/${encodeURIComponent(this.traceId)}/steps/${encodeURIComponent(sid)}/sensitive`,
          {credentials: "same-origin", cache: "no-store", signal: this.controller.signal,
           headers: {"X-Lumen-Language": this.locale?.startsWith("en") ? "en" : "es"}});
        const data = await response.json();
        if (generation !== this.requestGeneration || sid !== this.selected?.id) return;
        if (!response.ok) { this.inspectionError = data.message || this.t("No se pudo abrir la captura."); return; }
        this.inspection = data;
        this.sectionKey = data.sections[0]?.key || "";
        this.expiryTimer = setTimeout(() => this.hideSensitive(), Math.max(0, data.expires_at * 1000 - Date.now()));
        this.$nextTick(() => this.$refs.inspector?.scrollIntoView({block: "nearest"}));
      } catch (error) {
        if (error.name !== "AbortError" && generation === this.requestGeneration)
          this.inspectionError = this.t("No se pudo abrir la captura. Comprueba la sesión y vuelve a intentarlo.");
      } finally { if (generation === this.requestGeneration) this.loading = false; }
    },
    async openWorkbench() {
      if (!this.inspection) await this.revealSensitive();
      if (!this.inspection) return;
      this.workbench = true;
      this.loadRequest(this.inspection.requests?.[0]?.id);
      this.$nextTick(() => this.$refs.workbench?.scrollIntoView({block: "start", behavior: "smooth"}));
    },
    loadRequest(id) {
      this.templateId = id || "";
      const item = this.inspection?.requests?.find(r => r.id === id);
      this.replayResult = null; this.replayError = ""; this.exported = "";
      const isAuthHeader = key => /^(authorization|x-vault-token|x-api-key|api-key)$/i.test(key);
      const headers = item?.headers && Object.fromEntries(Object.entries(item.headers)
        .sort(([a], [b]) => Number(isAuthHeader(b)) - Number(isAuthHeader(a))));
      this.draft = item ? {method: item.method, url: item.url, headers: JSON.stringify(headers, null, 2),
        body: item.body, statement: item.statement, parameters: JSON.stringify(item.parameters, null, 2)} : null;
    },
    async sendRequest() {
      if (!this.draft || this.sending) return;
      const generation = this.requestGeneration, sid = this.selected?.id;
      this.replayResult = null; this.replayError = ""; this.sending = true;
      try {
        const payload = this.requestTemplate.kind === "http"
          ? {method: this.draft.method, url: this.draft.url, headers: JSON.parse(this.draft.headers), body: this.draft.body}
          : {statement: this.draft.statement, parameters: JSON.parse(this.draft.parameters)};
        payload.template_id = this.templateId;
        const response = await fetch(`/traces/${encodeURIComponent(this.traceId)}/steps/${encodeURIComponent(sid)}/replay`,
          {method: "POST", credentials: "same-origin", cache: "no-store", signal: this.controller.signal,
           headers: {"Content-Type": "application/json", "X-Lumen-Language": this.locale?.startsWith("en") ? "en" : "es"},
           body: JSON.stringify(payload)});
        const data = await response.json();
        if (generation !== this.requestGeneration || sid !== this.selected?.id) return;
        if (!response.ok) this.replayError = data.message || this.t("No se pudo ejecutar la petición.");
        else this.replayResult = data;
      } catch (error) {
        if (generation === this.requestGeneration && error.name !== "AbortError")
          this.replayError = error instanceof SyntaxError ? this.t("Revisa el JSON de las cabeceras o los parámetros.") : this.t("No se pudo ejecutar la petición.");
      } finally { if (generation === this.requestGeneration) this.sending = false; }
    },
    async copyCurl() {
      if (!this.draft || this.requestTemplate?.kind !== "http") return;
      try {
        const quote = value => "'" + String(value).replaceAll("'", "'\\''") + "'";
        const headers = JSON.parse(this.draft.headers);
        const command = ["curl --silent --show-error --max-time 60 --request", quote(this.draft.method), quote(this.draft.url)];
        for (const [key, value] of Object.entries(headers)) command.push("--header", quote(key + ": " + value));
        if (this.draft.body) command.push("--data-raw", quote(this.draft.body));
        await navigator.clipboard.writeText(command.join(" "));
        this.exported = this.t("cURL copiado. Para Vault, usa su CA de confianza en tu cliente.");
      } catch (_) { this.exported = this.t("No se pudo copiar. Revisa las cabeceras JSON."); }
    },
    exportPostman() {
      if (!this.draft || this.requestTemplate?.kind !== "http") return;
      try {
        const collection = {info: {name: "Lumen · " + this.selected.title,
          schema: "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          item: [{name: this.selected.title, request: {method: this.draft.method, url: this.draft.url,
            header: Object.entries(JSON.parse(this.draft.headers)).map(([key, value]) => ({key, value})),
            ...(this.draft.body ? {body: {mode: "raw", raw: this.draft.body}} : {})}}]};
        const url = URL.createObjectURL(new Blob([JSON.stringify(collection, null, 2)], {type: "application/json"}));
        const link = document.createElement("a"); link.href = url; link.download = "lumen-request.postman_collection.json";
        link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
        this.exported = this.t("Colección exportada con las credenciales visibles en la consola.");
      } catch (_) { this.exported = this.t("No se pudo copiar. Revisa las cabeceras JSON."); }
    },
    async copySection() {
      if (!this.section) return;
      const generation = this.requestGeneration, key = this.section.key;
      try {
        await navigator.clipboard.writeText(this.format(this.section.value));
        if (generation === this.requestGeneration && key === this.sectionKey) this.copied = this.t("Copiado");
      } catch (_) { this.copied = this.t("Selecciona el texto para copiarlo"); }
    },
    move(delta) {
      const next = this.visible[this.position + delta];
      if (next) {
        this.select(next);
        this.$nextTick(() => this.$refs.diagram.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
      }
    },
    changeFilter() { this.hideSensitive(); this.closeVaultDecision(); this.selectedId = this.visible[0]?.id; },
  },
  template: `
    <section class="tf" :aria-label="t('Flujo interactivo de llamadas')">
      <header class="tf-heading">
        <div><div class="tf-eyebrow">{{ t('RECORRIDO DE ESTA EJECUCIÓN') }}</div><h2>{{ flow.title }}</h2></div>
        <div class="tf-metrics">
          <div><strong>{{ flow.calls.length }}</strong><span>{{ t('llamadas registradas') }}</span></div>
          <div><strong>{{ ms(flow.duration_ms) }}</strong><span>{{ t('tiempo total de la traza') }}</span></div>
        </div>
      </header>
      <p class="tf-intro">{{ t('Lee de arriba abajo. Lumen hace las llamadas; cada columna es el servicio que las recibe. Selecciona una flecha para ver el intercambio.') }}</p>
      <p v-if="flow.incomplete" class="tf-notice">{{ t('La traza está incompleta: faltan operaciones padre. Se muestran los registros disponibles.') }}</p>
      <p v-if="flow.local_errors" class="tf-notice">{{ t('Hay errores en {count} operación(es) interna(s) o contenedora(s). Puedes revisarlos al desplegar las operaciones internas, aunque una llamada haya devuelto HTTP 200.', {count: flow.local_errors}) }}</p>
      <div class="tf-toolbar">
        <label>{{ t('Destino') }}
          <select :aria-label="t('Filtrar por destino')" v-model="filter" @change="changeFilter">
            <option value="all">{{ t('Todos los servicios') }}</option>
            <option v-for="a in flow.actors.filter(a => a.id !== 'lumen')" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </label>
        <label class="tf-checkbox"><input type="checkbox" v-model="returns"> {{ t('Mostrar retorno') }}</label>
        <span class="tf-legend">{{ t('→ Petición') }} <span v-if="returns">{{ t('⇠ Retorno registrado') }}</span></span>
      </div>
      <div v-if="flow.calls.length" class="tf-layout">
        <div class="tf-diagram" ref="diagram" tabindex="0" :aria-label="t('Diagrama de secuencia; desplazamiento horizontal disponible')">
          <div class="tf-canvas" :style="{minWidth: Math.max(620, flow.actors.length * 165) + 'px'}">
            <div class="tf-actors" :style="{gridTemplateColumns: 'repeat(' + flow.actors.length + ', 1fr)'}">
              <div v-for="a in flow.actors" :key="a.id" class="tf-actor" :class="{'tf-actor-active': a.id === 'lumen' || a.id === selected?.target}">
                <span class="tf-actor-dot"></span>
                <span class="tf-actor-label"><service-icon :service="a.id" :icons="icons"/><strong>{{ a.name }}</strong></span>
                <small>{{ a.description }}</small>
              </div>
            </div>
            <button v-for="call in visible" :key="call.id" type="button" class="tf-call"
                    :class="{'tf-selected': selected?.id === call.id, 'tf-failed': call.state === 'error'}"
                    :aria-pressed="selected?.id === call.id"
                    :aria-label="t('Paso {number}: Lumen a {actor}. {title}. {status}', {number: call.number, actor: actor(call.target), title: call.title, status: call.status})"
                    @click="select(call)">
              <svg viewBox="0 0 1000 116" preserveAspectRatio="none" aria-hidden="true">
                <line v-for="a in flow.actors" :key="a.id" :x1="x(a.id)" y1="0" :x2="x(a.id)" y2="116" class="tf-lifeline"/>
                <line :x1="x('lumen')" y1="65" :x2="x(call.target) - 3" y2="65" class="tf-out"/>
                <path :d="'M ' + (x(call.target)-10) + ' 59 L ' + x(call.target) + ' 65 L ' + (x(call.target)-10) + ' 71'" class="tf-arrow"/>
                <circle :cx="x('lumen')" cy="65" r="4" class="tf-origin"/>
                <template v-if="returns && call.response_recorded">
                  <line :x1="x(call.target)" y1="87" :x2="x('lumen')+3" y2="87" class="tf-return"/>
                  <path :d="'M ' + (x('lumen')+9) + ' 82 L ' + x('lumen') + ' 87 L ' + (x('lumen')+9) + ' 92'" class="tf-arrow tf-return-head"/>
                </template>
              </svg>
              <span class="tf-number">{{ call.number }}</span>
              <span class="tf-call-label" :style="{left: (x('lumen') / 10) + '%'}">
                <strong>{{ call.title }} <span class="tf-to">→ <service-icon :service="call.target" :icons="icons"/> {{ actor(call.target) }}</span></strong>
                <small>{{ call.method }} · {{ call.endpoint }}</small>
              </span>
              <span class="tf-call-result" :style="{left: (x('lumen') / 10) + '%'}">{{ call.status }} · {{ ms(call.duration_ms) }}</span>
            </button>
          </div>
        </div>
        <aside v-if="selected" class="tf-detail" :aria-label="t('Detalle de la llamada')" aria-live="polite">
          <div class="tf-step-nav">
            <span>{{ t('PASO {number} DE {count}', {number: selected.number, count: flow.calls.length}) }}</span>
            <div>
              <button type="button" :aria-label="t('Llamada anterior')" :disabled="position <= 0" @click="move(-1)">←</button>
              <button type="button" :aria-label="t('Llamada siguiente')" :disabled="position >= visible.length-1" @click="move(1)">→</button>
            </div>
          </div>
          <div class="tf-route">
            <span class="tf-route-actor"><service-icon service="lumen" :icons="icons"/>Lumen</span>
            <span class="tf-route-arrow">→</span>
            <span class="tf-route-actor"><service-icon :service="selected.target" :icons="icons"/>{{ actor(selected.target) }}</span>
          </div>
          <h3>{{ selected.title }}</h3>
          <div class="tf-status" :class="{'tf-error-status': selected.state === 'error'}">{{ selected.status }}</div>
          <section v-if="selected.target === 'vault' && traceId" class="tf-vault-decision">
            <button type="button" class="tf-vault-toggle" :aria-expanded="decisionOpen"
                    :aria-controls="'vault-decision-' + selected.id" @click="toggleVaultDecision">
              <span aria-hidden="true">{{ decisionOpen ? '▾' : '▸' }}</span> {{ t('Cómo decide Vault') }}
            </button>
            <div v-if="decisionOpen" :id="'vault-decision-' + selected.id" class="tf-vault-body"
                 role="region" :aria-label="t('Cómo decide Vault')" :aria-busy="decisionLoading">
              <p v-if="decisionLoading" role="status">{{ t('Consultando la auditoría de esta llamada…') }}</p>
              <p v-if="decisionError" role="alert">{{ decisionError }}</p>
              <template v-if="vaultDecision">
                <strong>{{ t(vaultDecision.mode_label) }}</strong>
                <p class="tf-vault-logic">{{ t(vaultDecision.logic) }}</p>
                <span class="tf-eyebrow">{{ t('DECISIÓN OBSERVADA') }}</span>
                <p>{{ t(vaultDecision.decision) }}</p>
                <template v-if="vaultDecision.audit_state === 'matched'">
                  <p class="tf-vault-source">{{ t('Fuente: auditoría de Vault correlacionada con esta llamada.') }}</p>
                  <p v-if="!vaultDecision.evidence.request_recorded || !vaultDecision.evidence.response_recorded" class="tf-note">{{ t('Evidencia parcial: falta el evento de petición o el de respuesta.') }}</p>
                  <dl>
                    <template v-if="vaultDecision.evidence.entity_id"><dt>{{ t('Entidad registrada por Vault') }}</dt><dd>{{ vaultDecision.evidence.entity_id }}</dd></template>
                    <template v-if="vaultDecision.evidence.actor"><dt>{{ t('Agente delegado') }}</dt><dd>{{ vaultDecision.evidence.actor }}</dd></template>
                    <dt>{{ t('Políticas que conceden acceso') }}</dt>
                    <dd v-if="vaultDecision.evidence.granting_policies.length">
                      <div v-for="policy in vaultDecision.evidence.granting_policies" :key="policy.namespace + policy.name"><code>{{ policy.name }}</code></div>
                    </dd><dd v-else>{{ t('No constan en este evento. Su ausencia no identifica una regla de denegación.') }}</dd>
                    <dt>{{ t('RAR registrado por Vault') }}</dt>
                    <dd v-if="vaultDecision.evidence.authorization_details.length">
                      <div v-for="(entry, index) in vaultDecision.evidence.authorization_details" :key="index" class="tf-vault-rar">
                        <code>{{ entry.path }}</code><br>{{ entry.capabilities.join(', ') }}
                        <small v-for="key in ['allowed_parameters', 'denied_parameters', 'required_parameters'].filter(k => entry[k])" :key="key"><br>{{ key }}: {{ entry[key].join(', ') }}</small>
                      </div>
                      <small>{{ t('Las restricciones de parámetros muestran los nombres de los campos, sin sus valores.') }}</small>
                    </dd><dd v-else>{{ t('Sin RAR legible en esta evidencia; no se presupone que fuera obligatorio ni que se evaluara.') }}</dd>
                  </dl>
                  <details class="tf-vault-evidence"><summary>{{ t('Evidencia de la decisión') }}</summary>
                    <pre tabindex="0"><code>{{ format(vaultDecision.evidence) }}</code></pre>
                  </details>
                </template>
                <p v-else class="tf-note">{{ t(vaultDecision.audit_state === 'ambiguous'
                  ? 'Hay registros incompatibles; no se atribuye una decisión a esta llamada.'
                  : vaultDecision.audit_state === 'limited' ? 'La consulta excede el límite de evidencia; no se presenta un resultado incompleto como concluyente.'
                  : vaultDecision.audit_state === 'unavailable' ? 'La auditoría no está disponible. No se ha repetido la operación en Vault.'
                  : 'No se encontró auditoría correlacionada. Puede estar pendiente de ingestión o fuera de retención.') }}</p>
                <p class="tf-note">{{ t(vaultDecision.note) }}</p>
              </template>
              <button v-if="!decisionLoading && (decisionError || vaultDecision?.audit_state !== 'matched')" class="tf-vault-toggle" type="button" @click="retryVaultDecision">{{ t('Volver a consultar') }}</button>
            </div>
          </section>
          <section v-if="selected.approval" class="tf-rar-summary">
            <strong>{{ t(selected.approval.operation === 'contract' ? 'Autorización de la contratación' : 'Autorización del PDF') }}</strong>
            <p>{{ t('Referencia') }}: {{ selected.approval.application }}</p>
            <p>{{ t('Petición de aprobación') }}: {{ selected.approval.id }}</p>
            <p>{{ t('Solicitante') }}: {{ selected.approval.requestor }}</p>
            <p>{{ t('Validador') }}: {{ selected.approval.validator }}</p>
            <p v-if="selected.approval.sha256" class="tf-mono">SHA-256: {{ selected.approval.sha256 }}</p>
          </section>
          <section v-if="selected.rar" class="tf-rar-summary">
            <strong>{{ t(selected.rar.phase === 'baseline' ? 'Control sin parámetros' : 'Con parámetros RAR') }}</strong>
            <p>{{ t(selected.rar.scenario) }} · {{ t(selected.rar.case) }}</p>
            <p>{{ t('El RAR y la petición de prueba se muestran debajo del diagrama.') }}</p>
          </section>
          <button v-if="labEnabled && traceId" class="tf-reveal" type="button" :aria-expanded="inspecting"
                  @click="inspecting ? hideSensitive() : revealSensitive()">{{ t(inspecting ? "Ocultar valores sensibles" : "Ver valores sensibles") }}</button>
          <p v-else class="tf-note">{{ t('La captura sensible requiere el modo laboratorio y una nueva ejecución.') }}</p>
          <button v-if="labEnabled && traceId" type="button" class="tf-reveal tf-console-button" @click="openWorkbench">{{ t("Abrir consola de peticiones") }}</button>
          <section v-if="selected.agent_name" class="tf-agent" :aria-label="t('Agente en Vault')">
            <span class="tf-eyebrow">{{ t('Agente en Vault') }}</span>
            <strong>{{ selected.agent_name }}</strong>
            <p class="tf-agent-context">{{ t(['mysql', 'openai', 'anthropic', 'xai', 'tavily'].includes(selected.target) ? 'Agente que obtuvo la credencial; el servicio destino no recibe una entidad de Vault.' : 'Identidad del agente utilizada en este flujo.') }}</p>
            <template v-if="selected.agent">
              <nav class="tf-agent-links" :aria-label="t('Enlaces a Vault')">
                <a :href="selected.agent.registry_url" target="_blank" rel="noopener noreferrer">{{ t('Abrir Agent Registry') }} ↗</a>
                <a v-if="selected.agent.entity_url" :href="selected.agent.entity_url" target="_blank" rel="noopener noreferrer">{{ t('Abrir entidad en Vault') }} ↗</a>
              </nav>
              <p v-if="!selected.agent.available">{{ t(selected.agent.message) }}</p>
              <details v-else :key="selected.id" class="tf-agent-details">
                <summary>{{ t('Agente, políticas, entidad y alias') }}</summary>
                <p>{{ t('Metadatos actuales al abrir la traza; no son una instantánea histórica.') }}</p>
                <small>{{ selected.agent.checked_at }}</small>
                <dl><template v-for="field in selected.agent.fields" :key="field[0]"><dt>{{ t(field[0]) }}</dt><dd>{{ t(field[1]) }}</dd></template></dl>
                <h4>{{ t('Políticas del agente') }}</h4>
                <p>{{ t('El techo OBO limita la delegación; los permisos efectivos dependen también del usuario y del RAR.') }}</p>
                <details v-for="policy in selected.agent.policies" :key="policy.name" class="tf-policy">
                  <summary>{{ policy.name }}</summary>
                  <p>{{ policy.levels.map(level => t(level)).join(' · ') }}</p>
                  <a :href="policy.url" target="_blank" rel="noopener noreferrer">{{ t('Abrir política en Vault') }} ↗</a>
                  <pre v-if="policy.available" tabindex="0"><code>{{ policy.hcl }}</code></pre>
                  <p v-else>{{ t('Contenido de la política no disponible para el inspector.') }}</p>
                </details>
                <h4>{{ t('Detalles de la entidad') }}</h4>
                <dl><template v-for="field in selected.agent.entity_fields" :key="field[0]"><dt>{{ t(field[0]) }}</dt><dd>{{ t(field[1]) }}</dd></template></dl>
                <section v-for="alias in selected.agent.aliases" :key="alias.id">
                  <h4>Alias · <a :href="alias.url" target="_blank" rel="noopener noreferrer">{{ alias.name }} ↗</a></h4>
                  <dl><template v-for="field in alias.fields" :key="field[0]"><dt>{{ t(field[0]) }}</dt><dd>{{ t(field[1]) }}</dd></template></dl>
                </section>
              </details>
              <small>{{ t('Los enlaces abren Vault con tu propia sesión; no incluyen tokens de Lumen.') }}</small>
            </template>
          </section>
          <dl>
            <dt>{{ t('Destino de la operación') }}</dt><dd class="tf-endpoint">{{ selected.method }} {{ selected.endpoint }}</dd>
            <dt>{{ t('Qué envía Lumen') }}</dt><dd>{{ selected.request }}</dd>
            <dt>{{ t('Con qué se autentica') }}</dt><dd>{{ selected.credential }}</dd>
            <dt>{{ t('Respuesta prevista por el cliente') }}</dt><dd>{{ selected.response }}</dd>
          </dl>
          <p v-if="selected.state === 'error'" class="tf-notice">{{ t('La operación terminó con error. La respuesta prevista no acredita que se haya recibido o validado.') }}</p>
          <p v-else-if="!selected.response_recorded" class="tf-notice">{{ t('No hay respuesta HTTP registrada para esta operación.') }}</p>
          <div class="tf-times"><div><span>{{ t('Inicio del span') }}</span><strong>+{{ ms(selected.start_ms) }}</strong></div><div><span>{{ t('Duración del span') }}</span><strong>{{ ms(selected.duration_ms) }}</strong></div></div>
          <p v-for="note in selected.notes" :key="note" class="tf-note">{{ note }}</p>
          <details class="tf-evidence"><summary>{{ t('Referencia técnica') }}</summary>
            <dl><dt>Span</dt><dd>{{ selected.name }}</dd><dt>Span ID</dt><dd>{{ selected.id }}</dd>
              <template v-if="selected.request_id"><dt>{{ t('Request ID de Vault') }}</dt><dd>{{ selected.request_id }}</dd></template>
              <dt>{{ t('Operaciones que lo contienen') }}</dt><dd>{{ selected.context || t('Sin operación padre disponible') }}</dd>
            </dl>
          </details>
        </aside>
      </div>
      <p v-else class="tf-notice">{{ t('No hay llamadas externas reconocidas en los registros disponibles. Revisa las operaciones internas y la tabla técnica.') }}</p>
      <section v-if="personal" class="tf-rar-panel tf-personal" :aria-label="t('Aislamiento del espacio personal')">
        <header class="tf-personal-heading">
          <div><div class="tf-eyebrow">{{ t('IDENTIDAD → POLÍTICA → RUTA') }}</div><h3>{{ t('Aislamiento del espacio personal') }}</h3></div>
          <span class="tf-status" :class="{'tf-error-status': selected.state === 'error'}">{{ actor(selected.target) }} · {{ selected.status }}</span>
        </header>
        <p>{{ t('El UUID lo genera Vault al crear la entidad humana. Cuando llega una petición OBO, Vault recupera esa entidad mediante el alias del usuario identificado por Verify; no toma la identidad de la URL solicitada.') }}</p>
        <div class="tf-personal-identities">
          <div><span class="tf-eyebrow">{{ t('USUARIO QUE DELEGA') }}</span><strong>{{ personal.owner_name || t('Usuario de esta ejecución') }}</strong><code>{{ personal.owner_entity }}</code><small>{{ t('UUID humano usado para expandir la política') }}</small></div>
          <div><span class="tf-eyebrow">{{ t('PROPIETARIO DE LA RUTA') }}</span><strong>{{ personal.target_name || t('Espacio solicitado') }}</strong><code>{{ personal.target_entity }}</code><small>{{ t('UUID presente en la ruta pedida por Lumen') }}</small></div>
        </div>
        <ol class="tf-personal-steps">
          <li><span class="tf-personal-number" aria-hidden="true">1</span><div><h4>{{ t('Se prepara la identidad') }}</h4>
            <p>{{ t('El instalador crea la entidad en Vault y un alias que une el emisor de Verify y el ID del usuario con el canonical_id de esa entidad. Son dos identificadores distintos.') }}</p>
            <dl><dt>iss / issuer</dt><dd>{{ personal.issuer || t('No registrado en esta traza') }}</dd><dt>sub / external_id</dt><dd>{{ personal.subject || t('No registrado en esta traza') }}</dd><dt>canonical_id → entity.id</dt><dd>{{ personal.owner_entity }}</dd></dl>
          </div></li>
          <li><span class="tf-personal-number" aria-hidden="true">2</span><div><h4>{{ t('Se guarda bajo ese UUID') }}</h4>
            <p>{{ t('El instalador crea demo bajo lumen-personal/UUID/demo con su credencial de aprovisionamiento. Después, Lumen construye las rutas con el catálogo de identidades; guardar desde la pantalla usa OBO.') }}</p>
            <p>{{ t('El campo owner del JSON es informativo. La protección viene de la ruta y de las políticas, no de quién escribió el valor inicial.') }}</p>
          </div></li>
          <li><span class="tf-personal-number" aria-hidden="true">3</span><div><h4>{{ t('Verify firma la delegación') }}</h4>
            <p>{{ t('Lumen envía el token humano, el token del agente y el RAR para la operación. Verify devuelve un JWT OBO firmado: sub identifica al humano y actor-token.sub al agente.') }}</p>
            <dl><dt>{{ t('Agente en este flujo') }}</dt><dd>{{ selected.agent_name || t('No registrado en esta traza') }}</dd><dt>actor-token.sub / client_id</dt><dd>{{ personal.actor_client_id || t('No registrado en esta traza') }}</dd></dl>
          </div></li>
          <li><span class="tf-personal-number" aria-hidden="true">4</span><div><h4>{{ t('Vault resuelve y autoriza') }}</h4>
            <p>{{ t('Lumen presenta el JWT en X-Vault-Token. Vault valida firma, emisor y vigencia; el perfil OAuth usa user_claim=sub y actor_claim=actor-token.sub. El alias resuelve al humano y al agente por separado.') }}</p>
            <p>{{ t('Vault obtiene las políticas humanas, sustituye identity.entity.id por el UUID humano y comprueba también el techo del agente y el RAR.') }}</p>
          </div></li>
        </ol>
        <div class="tf-personal-comparison">
          <div><h4>{{ t('Aplicado a esta petición') }}</h4><p>{{ t('Política humana ∩ techo del agente ∩ RAR del token') }}</p></div>
          <span class="tf-personal-match" :class="{'tf-personal-different': personal.path_matches_owner === false}">{{ t(personal.path_matches_owner === true ? 'Mismo UUID: espacio propio' : personal.path_matches_owner === false ? 'UUID distinto: espacio ajeno' : 'Faltan datos para comparar la ruta') }}</span>
        </div>
        <div class="tf-personal-paths">
          <div><h4>{{ t('Plantilla de la política humana') }}</h4><code>{{ personal.template_path || t('No registrado en esta traza') }}</code></div>
          <div><h4>{{ t('Plantilla expandida para este humano') }}</h4><code>{{ personal.expanded_path || t('No registrado en esta traza') }}</code></div>
          <div><h4>{{ t('Ruta solicitada') }}</h4><code>{{ personal.path }}</code></div>
        </div>
        <p class="tf-personal-rule" v-if="personal.path_matches_owner !== undefined">{{ t(personal.path_matches_owner ? 'La ruta está dentro del espacio propio. Esto no garantiza el acceso: Consulta y Revelado, por ejemplo, no pueden escribir por su techo.' : 'La política personal mostrada no permite esta ruta ajena. Cambiar la URL o pedir esa ruta en el RAR no cambia la identidad humana resuelta desde el token.') }}</p>
        <p class="tf-notice">{{ t(personalOutcome) }}</p>
        <details class="tf-personal-more">
          <summary>{{ t('Por qué hay un wildcard en el Registry') }}</summary>
          <p>{{ t('El mismo agente atiende a varios usuarios. Su techo puede cubrir lumen-personal/*, pero cada usuario solo tiene lumen-personal/SU_UUID/*. En OBO se exige la intersección; el wildcard del agente no concede acceso a los espacios de todos.') }}</p>
          <p>{{ t('La política lumen-personal-user llega al humano mediante el grupo lumen-personal-users. Las políticas del Registry limitan al agente. El RAR acota la operación concreta; no amplía ninguna de las otras dos capas.') }}</p>
          <div class="tf-rar-json">
            <div><h4>{{ personal.user_policy }}</h4><pre v-if="personal.user_policy_snapshot" tabindex="0"><code>{{ personal.user_policy_snapshot }}</code></pre><p v-else>{{ t('Esta traza no guardó el HCL. La comparación superior ilustra la regla de la demo; abre Vault para consultar la política actual.') }}</p></div>
            <div><h4>{{ personal.ceiling_policy || t('Techo del agente') }}</h4><pre v-if="personal.ceiling_policy_snapshot" tabindex="0"><code>{{ personal.ceiling_policy_snapshot }}</code></pre><p v-else>{{ t('Esta traza no guardó el HCL. La comparación superior ilustra la regla de la demo; abre Vault para consultar la política actual.') }}</p></div>
          </div>
          <h4>{{ t(personal.rar_source === 'presented' ? 'RAR presentado a Vault' : 'RAR solicitado a Verify') }}</h4>
          <pre v-if="personal.authorization_details" tabindex="0"><code>{{ format(personal.authorization_details) }}</code></pre><p v-else>{{ t('No registrado en este paso. Selecciona el intercambio OBO o la petición a Vault para ver su RAR.') }}</p>
        </details>
        <details class="tf-personal-more">
          <summary>{{ t('Origen de los datos y cómo comprobarlo') }}</summary>
          <p>{{ t('Los nombres, UUID y snapshots HCL proceden del catálogo publicado por el instalador y registrado por Lumen en esta ejecución. La plantilla expandida es una explicación de esa configuración, no una lectura de la ACL efectiva de Vault.') }}</p>
          <p>{{ t('La respuesta HTTP de la llamada a Vault acredita el resultado observado. Para inspeccionar el token y la petición completos, usa Ver valores sensibles o Abrir consola de peticiones en ese paso. Las trazas antiguas dejan vacíos los datos que no registraron.') }}</p>
          <p>{{ t('Puedes comprobar el vínculo en Vault: perfil OAuth verify, alias de la entidad humana, grupo lumen-personal-users y política lumen-personal-user. El alias debe vincular issuer + external_id con el canonical_id humano.') }}</p>
          <div class="tf-personal-links"><a href="https://developer.hashicorp.com/vault/ai/iam/setup-obo" target="_blank" rel="noopener noreferrer">{{ t('Documentación de OBO') }} ↗</a><a href="https://developer.hashicorp.com/vault/docs/concepts/policies#templated-policies" target="_blank" rel="noopener noreferrer">{{ t('Plantillas de políticas de Vault') }} ↗</a></div>
        </details>
      </section>
      <section v-if="selected?.rar" class="tf-rar-panel" :aria-label="t('RAR y parámetros de esta comparación')">
        <div class="tf-eyebrow">{{ t('RAR y parámetros de esta comparación') }}</div>
        <h3>{{ t(selected.rar.phase === 'baseline' ? 'Control sin parámetros' : 'Con parámetros RAR') }} · {{ t(selected.rar.case) }}</h3>
        <p>{{ t('Mismo usuario, agente, ruta y cuerpo. Solo cambian las restricciones del token OBO. Las credenciales y el intercambio completo están en la consola de peticiones.') }}</p>
        <div class="tf-rar-json">
          <div><h4>authorization_details</h4><pre tabindex="0"><code>{{ format(selected.rar.authorization_details) }}</code></pre></div>
          <div><h4>{{ t('Petición de prueba a Vault') }}</h4><pre tabindex="0"><code>{{ format(selected.rar.payload) }}</code></pre></div>
        </div>
      </section>
      <section v-if="inspecting && selected && !workbench" class="tf-inspector" ref="inspector" :aria-label="t('Valores sensibles del paso')">
        <header class="tf-inspector-heading">
          <div><span class="tf-eyebrow">{{ t('MODO LABORATORIO · CAPTURA REAL') }}</span><h3>{{ t('Paso {number} · {title}', {number: selected.number, title: selected.title}) }}</h3></div>
          <button type="button" class="tf-small-button" @click="hideSensitive()">{{ t('Ocultar valores') }}</button>
        </header>
        <p v-if="loading" role="status">{{ t('Cargando los valores de este paso…') }}</p>
        <p v-if="inspectionError" role="alert" class="tf-notice">{{ inspectionError }}</p>
        <template v-if="inspection">
          <p v-if="inspection.message" class="tf-notice">{{ inspection.message }}</p>
          <div v-if="inspection.sections.length" class="tf-inspector-grid">
            <nav :aria-label="t('Contenido de la captura')">
              <button v-for="s in inspection.sections" :key="s.key" type="button"
                      :aria-pressed="sectionKey === s.key" :class="{'tf-section-active': sectionKey === s.key}"
                      @click="sectionKey = s.key; copied = ''">{{ s.title }}<small>{{ t(s.source === 'derived' ? 'Derivado del valor capturado' : 'Valor registrado en esta llamada') }}</small></button>
            </nav>
            <div v-if="section" class="tf-value">
              <div class="tf-value-heading"><strong>{{ section.title }}</strong><button class="tf-small-button" type="button" @click="copySection">{{ copied || t("Copiar valor") }}</button></div>
              <p v-if="section.truncated" class="tf-notice">{{ t('Captura truncada por el límite de tamaño. Este contenido no representa el valor completo.') }}</p>
              <p v-if="section.source === 'derived'" class="tf-value-note">{{ t('Decodificado a partir del valor de esta llamada. El original se conserva en la petición o respuesta.') }}</p>
              <pre tabindex="0" :aria-label="t('Valor capturado')"><code>{{ format(section.value) }}</code></pre>
            </div>
          </div>
          <p class="tf-inspection-note">{{ inspection.note }} {{ t('Al cambiar de paso o de pestaña se ocultan los valores.') }}</p>
        </template>
      </section>
      <section v-if="workbench && inspection && selected" class="tf-workbench tf-inspector" ref="workbench" :aria-label="t('Consola de peticiones')">
        <header class="tf-inspector-heading">
          <div><span class="tf-eyebrow">{{ t('EMULAR ESTA LLAMADA') }}</span><h3>{{ t('Consola de peticiones') }} · {{ selected.title }}</h3></div>
          <button type="button" class="tf-small-button" @click="hideSensitive()">{{ t('Cerrar consola') }}</button>
        </header>
        <p>{{ t('Precargada con la petición real. Editar no ejecuta nada. Enviar realiza una nueva llamada con estos valores, sin renovar tokens ni ejecutar las herramientas que proponga el modelo.') }}</p>
        <p v-if="!inspection.requests?.length" class="tf-notice">{{ t('Este paso no tiene una captura completa reproducible. Genera una nueva traza. Las operaciones internas no son peticiones HTTP.') }}</p>
        <template v-if="draft && requestTemplate">
          <div class="tf-workbench-toolbar">
            <label>{{ t('Petición capturada') }}<select :aria-label="t('Petición capturada')" :value="templateId" :disabled="sending" @change="loadRequest($event.target.value)">
              <option v-for="r in inspection.requests" :key="r.id" :value="r.id">{{ r.kind === 'http' ? t('Intento {number}', {number: r.attempt}) + ' · ' + r.method : 'MySQL · SQL' }}</option>
            </select></label>
            <button type="button" class="tf-small-button" :disabled="sending" @click="loadRequest(templateId)">{{ t('Restaurar captura') }}</button>
          </div>
          <fieldset :disabled="sending">
            <template v-if="requestTemplate.kind === 'http'">
              <div class="tf-http-address">
                <label>{{ t('Método') }}<select v-model="draft.method" :aria-label="t('Método HTTP')"><option v-for="method in ['GET','POST','PUT','PATCH','DELETE','LIST','HEAD','OPTIONS']" :key="method">{{ method }}</option></select></label>
                <label>URL<input v-model="draft.url" aria-label="URL" autocomplete="off" spellcheck="false"></label>
              </div>
              <label class="tf-request-headers"><strong>{{ t('Cabeceras y autenticación · JSON') }}</strong>
                <textarea v-model="draft.headers" :aria-label="t('Cabeceras y autenticación · JSON')" rows="10" spellcheck="false" autocomplete="off"></textarea>
              </label>
              <label>{{ t('Cuerpo enviado · mensajes, instrucciones y herramientas') }}
                <textarea v-model="draft.body" :aria-label="t('Cuerpo enviado · mensajes, instrucciones y herramientas')" rows="16" spellcheck="false" autocomplete="off"></textarea>
              </label>
              <p class="tf-value-note">{{ t('Se conserva el texto enviado, incluido el formato JSON o formulario. El cliente recalcula Host y Content-Length. La URL debe permanecer en el mismo servidor, protocolo y puerto; no se siguen redirecciones.') }}</p>
            </template>
            <template v-else>
              <p>{{ t('MySQL usa su protocolo SQL. La conexión conserva el servidor, la base de datos y la credencial dinámica de este paso.') }}</p>
              <section class="tf-mysql-auth" :aria-label="t('Autenticación MySQL')">
                <h4>{{ t('Autenticación MySQL') }}</h4>
                <p>{{ t('Usuario y contraseña dinámicos emitidos por Vault para esta llamada. La repetición usa estos mismos valores.') }}</p>
                <div class="tf-mysql-connection">
                  <label v-for="[key, title] in [['host', 'Servidor MySQL'], ['port', 'Puerto MySQL'], ['database', 'Base de datos MySQL'], ['username', 'Usuario MySQL'], ['password', 'Contraseña MySQL']]"
                         :key="key" :class="{'tf-mysql-password': key === 'password'}">
                    {{ t(title) }}
                    <input type="text" :value="requestTemplate.connection[key]" :aria-label="t(title)" readonly autocomplete="off" spellcheck="false">
                  </label>
                </div>
                <p v-if="requestTemplate.connection.lease_duration != null" class="tf-value-note">{{ t('Validez al emitir: {seconds} s', {seconds: requestTemplate.connection.lease_duration}) }}</p>
                <p v-if="requestTemplate.connection.lease_id" class="tf-mysql-lease">Lease ID · <code>{{ requestTemplate.connection.lease_id }}</code></p>
              </section>
              <label>SQL<textarea v-model="draft.statement" aria-label="SQL" rows="5" spellcheck="false"></textarea></label>
              <label>{{ t('Parámetros SQL · JSON') }}<textarea v-model="draft.parameters" :aria-label="t('Parámetros SQL · JSON')" rows="4" spellcheck="false"></textarea></label>
            </template>
          </fieldset>
          <p class="tf-notice">{{ t('Enviar puede consumir el modelo, emitir credenciales o modificar datos. Las escrituras SQL se confirman. Los tokens caducados y los códigos de un solo uso devuelven el error real del servicio.') }}</p>
          <div class="tf-workbench-actions">
            <button type="button" class="tf-reveal" :disabled="sending" @click="sendRequest">{{ t(sending ? 'Enviando…' : 'Enviar petición real') }}</button>
            <template v-if="requestTemplate.kind === 'http'">
              <button type="button" class="tf-small-button" @click="copyCurl">{{ t('Copiar cURL') }}</button>
              <button type="button" class="tf-small-button" @click="exportPostman">{{ t('Exportar a Postman') }}</button>
            </template>
          </div>
          <p v-if="exported" role="status">{{ exported }}</p>
          <p v-if="sending" role="status">{{ t('Petición en curso. Cerrar la consola no deshace la operación enviada.') }}</p>
          <p v-if="replayError" role="alert" class="tf-notice">{{ replayError }}</p>
          <section v-if="replayResult" class="tf-replay-result" :aria-label="t('Respuesta de la repetición')">
            <h4>{{ t('Respuesta de la repetición') }} · {{ replayResult.kind === 'http' ? 'HTTP ' + replayResult.status_code : 'MySQL' }} · {{ ms(replayResult.duration_ms) }}</h4>
            <p>{{ t('Esta respuesta pertenece a la repetición; no sustituye la traza ni la sesión originales.') }}</p>
            <p v-if="replayResult.truncated" class="tf-notice">{{ t('Respuesta limitada a 1 MiB o 50 filas de MySQL.') }}</p>
            <details v-if="replayResult.headers"><summary>{{ t('Cabeceras de respuesta') }}</summary><pre><code>{{ format(replayResult.headers) }}</code></pre></details>
            <pre tabindex="0"><code>{{ replayResult.kind === 'http' ? replayResult.body : format(replayResult) }}</code></pre>
          </section>
        </template>
      </section>
      <div class="tf-footer">
        <span v-if="!flow.model_calls">{{ t('Esta traza no registra llamadas al modelo.') }}</span>
        <span v-else>{{ t('{count} llamada(s) al modelo en esta traza.', {count: flow.model_calls}) }}</span>
        <span>{{ t('Los tiempos de spans anidados se solapan; no se suman al total. El diagrama no representa operaciones internas de los servicios remotos.') }}</span>
      </div>
      <details class="tf-local">
        <summary>{{ t('Operaciones internas y spans contenedores · {count}', {count: flow.local.length}) }}</summary>
        <p>{{ t('Coordinan las llamadas o procesan resultados dentro de Lumen. Una operación desconocida también se conserva aquí, sin inventar un destino.') }}</p>
        <ul><li v-for="op in flow.local" :key="op.id">
          <div><strong>{{ op.title }}</strong><code>{{ op.name }}</code></div>
          <span>{{ ms(op.duration_ms) }} · {{ op.status }}</span>
        </li></ul>
      </details>
    </section>`,
};

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
  props: { flow: Object, icons: Object, traceId: String, labEnabled: Boolean, messages: Object, locale: String },
  data() { return { selectedId: this.flow.calls[0]?.id, filter: "all", returns: true,
    inspection: null, inspecting: false, loading: false, inspectionError: "", sectionKey: "", copied: "",
    requestGeneration: 0, controller: null, expiryTimer: null }; },
  mounted() {
    this.onVisibility = () => { if (document.hidden) this.hideSensitive(); };
    document.addEventListener("visibilitychange", this.onVisibility);
  },
  beforeUnmount() {
    this.hideSensitive();
    document.removeEventListener("visibilitychange", this.onVisibility);
  },
  computed: {
    visible() { return this.flow.calls.filter(c => this.filter === "all" || c.target === this.filter); },
    selected() { return this.visible.find(c => c.id === this.selectedId) || this.visible[0]; },
    position() { return this.visible.findIndex(c => c.id === this.selected?.id); },
    section() { return this.inspection?.sections.find(s => s.key === this.sectionKey); },
  },
  methods: {
    t(text, values = {}) {
      const translated = this.messages?.[text] || text;
      return translated.replace(/\{(\w+)\}/g, (match, key) => Object.hasOwn(values, key) ? String(values[key]) : match);
    },
    actor(id) { return this.flow.actors.find(a => a.id === id)?.name || id; },
    x(id) { return (this.flow.actors.findIndex(a => a.id === id) + 0.5) * 1000 / this.flow.actors.length; },
    ms(value) { return new Intl.NumberFormat(this.locale || "es-ES", { maximumFractionDigits: 2 }).format(value) + " ms"; },
    select(call) { if (call.id !== this.selectedId) this.hideSensitive(); this.selectedId = call.id; },
    format(value) { return typeof value === "string" ? value : JSON.stringify(value, null, 2); },
    hideSensitive() {
      this.requestGeneration++;
      this.controller?.abort();
      clearTimeout(this.expiryTimer);
      this.inspection = null; this.inspecting = false; this.loading = false;
      this.inspectionError = ""; this.sectionKey = ""; this.copied = "";
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
    changeFilter() { this.hideSensitive(); this.selectedId = this.visible[0]?.id; },
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
          <button v-if="labEnabled && traceId" class="tf-reveal" type="button" :aria-expanded="inspecting"
                  @click="inspecting ? hideSensitive() : revealSensitive()">{{ t(inspecting ? "Ocultar valores sensibles" : "Ver valores sensibles") }}</button>
          <p v-else class="tf-note">{{ t('La captura sensible requiere el modo laboratorio y una nueva ejecución.') }}</p>
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
      <section v-if="inspecting && selected" class="tf-inspector" ref="inspector" :aria-label="t('Valores sensibles del paso')">
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

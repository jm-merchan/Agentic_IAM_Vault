export default {
  props: {snapshot: Object, messages: Object, icons: Object, locale: String, panelId: String},
  data() { return {expanded: false, trace: '', calls: [], actors: [], bottom: 18, panelWidth: 0, panelHeight: 400}; },
  computed: {
    lastDestination() { return this.calls.length ? this.actors.find(a => a.id === this.calls.at(-1).target)?.name : ''; },
    width() { return Math.max(276, this.actors.length * 92, this.panelWidth); },
    stateLabel() { return this.snapshot.busy ? this.messages.running : this.snapshot.traceId ?
      (this.snapshot.failed ? this.messages.failed : this.messages.done) : this.messages.waiting; },
  },
  watch: {snapshot: {immediate: true, handler(value) { this.sync(value); }}},
  methods: {
    sync(value) {
      const reset = this.trace !== value.traceId || !value.authenticated;
      if (reset) { this.calls = []; this.actors = []; this.trace = value.traceId || ''; }
      const seen = new Map(this.calls.map(c => [c.id, c]));
      // Retain object identity for existing arrows; a completed span updates its
      // return in place. A new trace never inherits arrows from its predecessor.
      let added = 0;
      this.calls = (value.calls || []).map(c => Object.assign(seen.get(c.id) || {delay: Math.min(added++ * 60, 240)}, c));
      for (const actor of value.actors || []) if (!this.actors.some(a => a.id === actor.id)) this.actors.push(actor);
      if (!value.authenticated) this.expanded = false;
      this.$nextTick?.(() => {
        if (this.expanded && this.$refs.scroll && this.followTail !== false)
          this.$refs.scroll.scrollTop = this.$refs.scroll.scrollHeight;
        this.place();
      });
    },
    x(id) { return (this.actors.findIndex(a => a.id === id) + .5) * this.width / Math.max(1, this.actors.length); },
    ms(value) { return new Intl.NumberFormat(this.locale, {maximumFractionDigits: 1}).format(value) + ' ms'; },
    result(call) {
      if (call.active) return this.messages.pending;
      return (call.http_status ? 'HTTP ' + call.http_status : call.response_recorded ? this.messages.finished : this.messages.noResponse)
        + ' · ' + this.ms(call.duration_ms);
    },
    toggle() {
      this.expanded = !this.expanded;
      this.followTail = true;
      this.$nextTick(() => this.place());
    },
    onScroll() {
      const el = this.$refs.scroll;
      this.followTail = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    },
    place() {
      if (!this.$el?.getBoundingClientRect) return;
      if (this.$refs.scroll) this.panelWidth = this.$refs.scroll.clientWidth;
      const composer = document.querySelector('.composer');
      const box = this.$el.getBoundingClientRect();
      const input = composer?.getBoundingClientRect();
      // Reserve space above the visible composer, including mobile keyboards.
      const viewport = window.visualViewport;
      const height = viewport ? viewport.height + viewport.offsetTop : window.innerHeight;
      const keyboard = Math.max(0, window.innerHeight - height);
      this.bottom = 18 + keyboard;
      this.panelHeight = (viewport?.height || window.innerHeight) * .45;
      if (input && input.top < height && input.bottom > 0 && input.right > box.left && input.left < box.right) {
        const above = input.top - (viewport?.offsetTop || 0) - 82;
        const below = height - input.bottom - 82;
        if (above >= 180 || above >= below) {
          this.bottom = Math.max(18 + keyboard, window.innerHeight - input.top + 12);
          this.panelHeight = Math.min(this.panelHeight, Math.max(100, above));
        } else {
          this.panelHeight = Math.min(this.panelHeight, Math.max(100, below));
        }
      }
    },
  },
  mounted() {
    this.followTail = true;
    this.reposition = () => this.place();
    this.escape = event => { if (event.key === 'Escape' && this.expanded) { this.expanded = false; this.$refs.toggle.focus(); } };
    window.addEventListener('resize', this.reposition);
    window.addEventListener('scroll', this.reposition, {passive: true, capture: true});
    window.visualViewport?.addEventListener('resize', this.reposition);
    document.addEventListener('keydown', this.escape);
    this.resizeObserver = new ResizeObserver(this.reposition);
    this.resizeObserver.observe(document.body);
    const composer = document.querySelector('.composer');
    if (composer) this.resizeObserver.observe(composer);
    this.place();
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.reposition);
    window.removeEventListener('scroll', this.reposition, true);
    window.visualViewport?.removeEventListener('resize', this.reposition);
    document.removeEventListener('keydown', this.escape);
    this.resizeObserver?.disconnect();
  },
  template: `
    <aside class="lcf" :class="{'lcf-expanded': expanded}" :style="{bottom: bottom + 'px'}" :aria-label="messages.title">
      <transition name="lcf-panel">
        <section v-if="expanded" :id="panelId" class="lcf-panel" :style="{maxHeight: panelHeight + 'px'}">
          <header class="lcf-heading"><div><div class="lcf-eyebrow">{{ messages.eyebrow }}</div>
            <h2>{{ messages.title }}</h2></div><span class="lcf-status" :class="{'lcf-running': snapshot.busy}" role="status">{{ stateLabel }}</span></header>
          <div v-if="!snapshot.authenticated" class="lcf-empty"><p>{{ messages.anonymous }}</p><a href="/auth/login">{{ messages.login }} ↗</a></div>
          <div v-else ref="scroll" class="lcf-scroll" tabindex="0" :aria-label="messages.scroll" @scroll="onScroll">
            <div class="lcf-sequence" :style="{width: width + 'px'}">
              <div class="lcf-actors">
                <div v-for="actor in actors" :key="actor.id" class="lcf-actor">
                  <span v-if="actor.id === 'lumen'" class="lcf-brand" aria-hidden="true"></span>
                  <img v-else :src="icons[actor.id]" alt="" width="20" height="20"><span>{{ actor.name }}</span>
                </div>
              </div>
              <div class="lcf-lines" aria-hidden="true"><i v-for="actor in actors" :key="actor.id" :style="{left: x(actor.id) + 'px'}"></i></div>
              <p v-if="!calls.length" class="lcf-empty">{{ snapshot.busy ? messages.waiting : messages.empty }}</p>
              <transition-group name="lcf-call" tag="div">
                <div v-for="(call, index) in calls" :key="trace + call.id" class="lcf-call" :style="{'transition-delay': call.delay + 'ms'}" :class="{'lcf-active': call.active, 'lcf-error': call.state === 'error'}">
                  <svg :viewBox="'0 0 ' + width + ' 70'" role="img" :aria-label="(index + 1) + '. Lumen → ' + call.target + ': ' + call.title + '. ' + result(call)">
                    <title>{{ call.title }} · {{ result(call) }}</title>
                    <text :x="x('lumen') + 8" y="13" class="lcf-call-title">{{ index + 1 }}. {{ call.title }}</text>
                    <path :d="'M ' + x('lumen') + ' 25 H ' + x(call.target)" class="lcf-outbound"/>
                    <path :d="'M ' + (x(call.target)-5) + ' 21 L ' + x(call.target) + ' 25 L ' + (x(call.target)-5) + ' 29'"/>
                    <circle :cx="x('lumen')" cy="25" r="3" class="lcf-origin"/>
                    <text v-if="call.active" :x="x('lumen') + 8" y="47" class="lcf-result">{{ messages.pending }}</text>
                    <g v-else class="lcf-return">
                      <text :x="x('lumen') + 8" y="47" class="lcf-result">{{ result(call) }}</text>
                      <path :d="'M ' + x(call.target) + ' 56 H ' + x('lumen')" stroke-dasharray="4 4"/>
                      <path :d="'M ' + (x('lumen')+5) + ' 52 L ' + x('lumen') + ' 56 L ' + (x('lumen')+5) + ' 60'"/>
                    </g>
                  </svg>
                </div>
              </transition-group>
            </div>
          </div>
          <footer v-if="snapshot.authenticated && snapshot.traceId && !snapshot.busy" class="lcf-footer">
            <a :href="'/traces/' + snapshot.traceId" target="_blank" rel="noopener noreferrer">{{ messages.trace }} ↗</a>
          </footer>
        </section>
      </transition>
      <button ref="toggle" type="button" class="lcf-chip" @click="toggle" :aria-expanded="expanded" :aria-controls="panelId" :aria-label="expanded ? messages.collapse : messages.expand">
        <span class="lcf-dot" :class="{'lcf-running': snapshot.busy, 'lcf-dot-error': snapshot.failed}" aria-hidden="true"></span>
        <span>{{ messages.title }}</span><span class="lcf-chip-meta">{{ calls.length }} {{ calls.length === 1 ? messages.hop : messages.hops }}<template v-if="lastDestination"> · {{ lastDestination }}</template></span>
        <span class="lcf-chevron" :class="{'lcf-chevron-open': expanded}" aria-hidden="true">⌃</span>
      </button>
    </aside>`,
};

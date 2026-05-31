window.ZERO = {
  tipo: 'store',

  init() {
    const promise = fetch('/api/sistema/tipo', {credentials: 'include'})
      .then(r => r.json())
      .then(data => { this.tipo = data.tipo || 'store'; })
      .catch(() => { this.tipo = 'store'; })
      .then(() => this.aplicarConfig());
    this._initPromise = promise;
    return promise;
  },

  isStore()   { return this.tipo === 'store'; },
  isFood()    { return this.tipo === 'food'; },
  isResto()   { return this.tipo === 'resto'; },
  isService() { return this.tipo === 'service'; },

  aplicarConfig() {
    const map = {
      '[data-solo-food]':    this.isFood(),
      '[data-solo-resto]':   this.isResto(),
      '[data-solo-store]':   this.isStore(),
      '[data-solo-service]': this.isService(),
    };
    for (const [sel, show] of Object.entries(map)) {
      document.querySelectorAll(sel).forEach(el => {
        el.style.display = show ? '' : 'none';
      });
    }
  },
};

ZERO.init();
